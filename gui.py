import customtkinter as ctk
import tkinter as tk  # need Listbox
from tkinter import filedialog, messagebox
import subprocess, os, json, re, webbrowser, getpass, platform, shutil
import ctypes
from ctypes import wintypes

try:
    import psutil
except ImportError:
    print("psutil missing, pip install psutil")
    psutil=None

# dll stuff, only on win
if platform.system()=="Windows":
    KERNEL32=ctypes.WinDLL('kernel32',use_last_error=True)

    PROCESS_CREATE_THREAD=0x0002
    PROCESS_QUERY_INFORMATION=0x0400
    PROCESS_VM_OPERATION=0x0008
    PROCESS_VM_WRITE=0x0020
    PROCESS_VM_READ=0x0010
    PROCESS_ALL_ACCESS_CUSTOM=(PROCESS_CREATE_THREAD|
                               PROCESS_QUERY_INFORMATION|
                               PROCESS_VM_OPERATION|
                               PROCESS_VM_WRITE|
                               PROCESS_VM_READ)

    MEM_COMMIT=0x1000
    MEM_RESERVE=0x2000
    MEM_COMMIT_RESERVE=MEM_COMMIT|MEM_RESERVE

    PAGE_EXECUTE_READWRITE=0x40

    KERNEL32.OpenProcess.restype=wintypes.HANDLE
    KERNEL32.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    KERNEL32.GetModuleHandleA.restype=wintypes.HMODULE
    KERNEL32.GetModuleHandleA.argtypes=(wintypes.LPCSTR,)
    KERNEL32.GetProcAddress.restype=ctypes.c_void_p
    KERNEL32.GetProcAddress.argtypes=(wintypes.HMODULE,wintypes.LPCSTR)
    KERNEL32.VirtualAllocEx.restype=wintypes.LPVOID
    KERNEL32.VirtualAllocEx.argtypes=(wintypes.HANDLE,wintypes.LPVOID,ctypes.c_size_t,wintypes.DWORD,wintypes.DWORD)
    KERNEL32.WriteProcessMemory.restype=wintypes.BOOL
    KERNEL32.WriteProcessMemory.argtypes=(wintypes.HANDLE,wintypes.LPVOID,wintypes.LPCVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t))
    KERNEL32.CreateRemoteThread.restype=wintypes.HANDLE
    KERNEL32.CreateRemoteThread.argtypes=(wintypes.HANDLE,ctypes.c_void_p,ctypes.c_size_t,wintypes.LPVOID,wintypes.LPVOID,wintypes.DWORD,wintypes.LPDWORD)
    KERNEL32.CloseHandle.restype=wintypes.BOOL
    KERNEL32.CloseHandle.argtypes=(wintypes.HANDLE,)

    INTPTR_ZERO=0

    class DLLInjector:
        def __init__(self):
            if platform.system()!="Windows":
                raise OSError("need windows")
            self.desired_access=PROCESS_ALL_ACCESS_CUSTOM
            self.allocation_type=MEM_COMMIT_RESERVE
            self.protection=PAGE_EXECUTE_READWRITE

        def inject_dll(self,process_id:int,dll_path:str)->bool:
            h_proc=KERNEL32.OpenProcess(self.desired_access,True,process_id)
            if not h_proc or h_proc==INTPTR_ZERO:
                print(f"cant open {process_id} err {ctypes.get_last_error()}")
                return False
            try:
                k32=KERNEL32.GetModuleHandleA(b"kernel32.dll")
                if not k32 or k32==INTPTR_ZERO:
                    print("no k32 handle")
                    return False
                load_lib=KERNEL32.GetProcAddress(k32,b"LoadLibraryA")
                if not load_lib or load_lib==INTPTR_ZERO:
                    print("cant get LoadLibraryA")
                    return False
                buf=ctypes.create_string_buffer(dll_path.encode('ascii'))
                size=ctypes.sizeof(buf)
                remote_ptr=KERNEL32.VirtualAllocEx(h_proc,None,size,self.allocation_type,self.protection)
                if not remote_ptr or remote_ptr==INTPTR_ZERO:
                    print("alloc fail")
                    return False
                try:
                    written=ctypes.c_size_t(0)
                    if not KERNEL32.WriteProcessMemory(h_proc,remote_ptr,buf,size,ctypes.byref(written)):
                        print("write fail")
                        return False
                    tid=wintypes.DWORD(0)
                    h_thread=KERNEL32.CreateRemoteThread(h_proc,None,0,load_lib,remote_ptr,0,ctypes.byref(tid))
                    if not h_thread or h_thread==INTPTR_ZERO:
                        print("thread fail")
                        return False
                    KERNEL32.CloseHandle(h_thread)
                    return True
                finally:
                    pass   # leak same as original
            finally:
                KERNEL32.CloseHandle(h_proc)

    DLL_INJECTOR_CLASS=DLLInjector
else:
    DLL_INJECTOR_CLASS=None
    DLLInjector=None
    KERNEL32=None


class RLOrbitalApp:
    VERSION="1.1.0"

    def __init__(self,root_window:ctk.CTk):
        self.root=root_window
        self.root.title("ReOrbital")
        self.root.geometry("330x520")
        self.root.resizable(False,False)

        self.dll_injector=DLL_INJECTOR_CLASS() if DLL_INJECTOR_CLASS else None

        self.config_path="config.json"
        self.rl_txt_path="rl.txt"
        self.accounts_dir=os.path.join(os.getcwd(),"Accounts")
        os.makedirs(self.accounts_dir,exist_ok=True)

        self.selected_bot_var=ctk.StringVar()
        self.selected_toggle_key_var=ctk.StringVar()

        self.speedflip_var=ctk.BooleanVar()
        self.bot_monitor_var=ctk.BooleanVar()
        self.bot_minimap_var=ctk.BooleanVar()
        self.bakkesmod_var=ctk.BooleanVar()
        self.clock_var=ctk.BooleanVar()
        self.debug_keys_var=ctk.BooleanVar()
        self.debugger_var=ctk.BooleanVar()

        self.status_label_var=ctk.StringVar(value="Not Running")

        self.rl_processes_pids_map={}
        self.bot_pids_for_rl={}

        self.rl_directory_var=ctk.StringVar()
        self.legendary_user_accounts_map={}

        self._create_widgets()
        self.load_initial_settings()

    def _create_widgets(self):
        self.notebook=ctk.CTkTabview(self.root)
        self.notebook.pack(expand=True,fill='both',padx=5,pady=5)

        self.tab1=self.notebook.add('Main')
        self._create_tab1_widgets()

        self.tab3=self.notebook.add('Launcher')
        self._create_tab3_widgets()

        self.tab2=self.notebook.add('Credits')
        self._create_tab2_widgets()

        self.root.after(10000,self.timer_check_injected_tick)

    def _create_tab1_widgets(self):
        ctk.CTkLabel(self.tab1,text="Select Bot").grid(row=0,column=0,padx=(0,5),pady=(0,2),sticky="sw")
        ctk.CTkLabel(self.tab1,text="Toggle Key").grid(row=0,column=1,padx=(5,0),pady=(0,2),sticky="sw")

        bots=["Nexto","Necto","Seer (old)","Element","NextMortal (air)","Genesis","Carbon"]
        self.combo_bot_selection=ctk.CTkComboBox(self.tab1,variable=self.selected_bot_var,
                                                 values=bots,state="readonly")
        self.combo_bot_selection.grid(row=1,column=0,padx=(0,5),pady=2,sticky="ew")

        toggle_keys=[
            "F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","A","B","C","D","E",
            "F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",
            "Escape","SpaceBar","PageUp","PageDown","End","Home","Insert","Delete","LeftShift",
            "RightShift","LeftControl","RightControl","LeftAlt","RightAlt","LeftCommand",
            "RightCommand","Zero","One","Two","Three","Four","Five","Six","Seven","Eight","Nine",
            "LeftMouseButton","RightMouseButton","MiddleMouseButton","ThumbMouseButton",
            "ThumbMouseButton2","XboxTypeS_Start","XboxTypeS_Back","XboxTypeS_X","XboxTypeS_Y",
            "XboxTypeS_A","XboxTypeS_B","XboxTypeS_DPad_Up","XboxTypeS_DPad_Down",
            "XboxTypeS_DPad_Right","XboxTypeS_DPad_Left","XboxTypeS_RightThumbStick",
            "XboxTypeS_LeftThumbStick","XboxTypeS_LeftTrigger","XboxTypeS_RightTrigger",
            "XboxTypeS_LeftShoulder","XboxTypeS_RightShoulder"]
        self.combo_toggle_keys=ctk.CTkComboBox(self.tab1, variable=self.selected_toggle_key_var,
                                               values=toggle_keys, state="readonly",
                                               command=self.combo_toggle_keys_selected_changed)
        self.combo_toggle_keys.grid(row=1,column=1,padx=(5,0),pady=2,sticky="ew")

        cb_frame=ctk.CTkFrame(self.tab1,fg_color="transparent")
        cb_frame.grid(row=2,column=0,columnspan=2,padx=0,pady=(10,5),sticky="ew")

        ctk.CTkCheckBox(cb_frame,text="SpeedFlip Kickoff",variable=self.speedflip_var).grid(row=0,column=0,sticky="w",pady=(0,2))
        ctk.CTkCheckBox(cb_frame,text="Bot Monitoring",variable=self.bot_monitor_var).grid(row=1,column=0,sticky="w",pady=(0,2))
        ctk.CTkCheckBox(cb_frame,text="Bot MiniMap (CPU)",variable=self.bot_minimap_var).grid(row=2,column=0,sticky="w",pady=(0,2))
        ctk.CTkCheckBox(cb_frame,text="BakkesMod",variable=self.bakkesmod_var).grid(row=3,column=0,sticky="w",pady=(0,2))

        ctk.CTkCheckBox(cb_frame,text="Clock",variable=self.clock_var).grid(row=0,column=1,sticky="w",padx=(20,0),pady=(0,2))
        ctk.CTkCheckBox(cb_frame,text="Debug Keys",variable=self.debug_keys_var).grid(row=1,column=1,sticky="w",padx=(20,0),pady=(0,2))
        ctk.CTkCheckBox(cb_frame,text="Debugger",variable=self.debugger_var).grid(row=2,column=1,sticky="w",padx=(20,0),pady=(0,2))
        cb_frame.columnconfigure(0,weight=1)
        cb_frame.columnconfigure(1,weight=1)

        ctk.CTkButton(self.tab1,text="Find Processes",command=self.button_find_processes_click).grid(row=3,column=0,columnspan=2,pady=5,sticky="ew")
        ctk.CTkLabel(self.tab1,text="Current Rocket League Processes Active:").grid(row=4,column=0,columnspan=2,sticky="w")

        lb_frame=ctk.CTkFrame(self.tab1)
        lb_frame.grid(row=5,column=0,columnspan=2,sticky="nsew")
        self.listbox_processes=tk.Listbox(lb_frame,height=5,exportselection=False,
                                          bg="#2A2D2E",fg="#DCE4EE",
                                          selectbackground="#1F6AA5",selectforeground="white",
                                          borderwidth=0,highlightthickness=0)
        self.listbox_processes.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        sb=ctk.CTkScrollbar(lb_frame,command=self.listbox_processes.yview)
        sb.pack(side=tk.RIGHT,fill=tk.Y)
        self.listbox_processes.configure(yscrollcommand=sb.set)

        ctk.CTkButton(self.tab1,text="Start Bot",command=self.button_start_bot_click).grid(row=6,column=0,padx=(0,5),pady=(10,5),sticky="ew")
        ctk.CTkButton(self.tab1,text="Stop Bot",command=self.button_stop_bot_click).grid(row=6,column=1,padx=(5,0),pady=(10,5),sticky="ew")

        stat_frame=ctk.CTkFrame(self.tab1,fg_color="transparent")
        stat_frame.grid(row=7,column=0,columnspan=2,sticky="w")
        ctk.CTkLabel(stat_frame,text="Status: ").pack(side=tk.LEFT)
        self.label_injected_status=ctk.CTkLabel(stat_frame,textvariable=self.status_label_var,text_color="red")
        self.label_injected_status.pack(side=tk.LEFT)

        self.tab1.columnconfigure(0,weight=1)
        self.tab1.columnconfigure(1,weight=1)
        self.tab1.rowconfigure(5,weight=1)

    def _create_tab2_widgets(self):
        credits=[("Marlburrow for RL Marlbot:","Marlbot 1.6.1","https://github.com/MarlBurroW"),
                 ("My Github:","","https://github.com/flaryx32"),
                 ("Skiffy for Orbital Gui:","","https://github.com/SkiffyMan"),
                 ("Derrod for Legendary Launcher:","","https://github.com/derrod"),
                 ("Xen for NextMortal:","","https://github.com/xenmods")]
        for i,(desc,ver,url) in enumerate(credits):
            frame=ctk.CTkFrame(self.tab2,fg_color="transparent")
            frame.grid(row=i,column=0,sticky="w",pady=2)
            txt=desc+(" "+ver if ver else "")
            ctk.CTkLabel(frame,text=txt).pack(side="left")
            if url:
                link=ctk.CTkLabel(frame,text="GitHub",text_color="deepskyblue",cursor="hand2")
                link.pack(side="left",padx=5)
                link.bind("<Button-1>",lambda e,u=url:self.open_browser(u))
        self.tab2.columnconfigure(0,weight=1)

    def _create_tab3_widgets(self):
        ctk.CTkLabel(self.tab3,text="Rocket League Directory").grid(row=0,column=0,columnspan=2,sticky="w")
        self.entry_rl_directory=ctk.CTkEntry(self.tab3,textvariable=self.rl_directory_var,state="readonly")
        self.entry_rl_directory.grid(row=1,column=0,padx=(0,5),pady=2,sticky="ew")
        ctk.CTkButton(self.tab3,text="...",command=self.button_select_rl_dir_click,width=30).grid(row=1,column=1)

        ul_frame=ctk.CTkFrame(self.tab3)
        ul_frame.grid(row=2,column=0,columnspan=2,pady=10,sticky="nsew")
        self.listbox_usernames=tk.Listbox(ul_frame,height=10,exportselection=False,
                                          bg="#2A2D2E",fg="#DCE4EE",
                                          selectbackground="#1F6AA5",selectforeground="white",
                                          borderwidth=0,highlightthickness=0)
        self.listbox_usernames.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        sb_u=ctk.CTkScrollbar(ul_frame,command=self.listbox_usernames.yview)
        sb_u.pack(side=tk.RIGHT,fill=tk.Y)
        self.listbox_usernames.configure(yscrollcommand=sb_u.set)

        ctk.CTkButton(self.tab3,text="Add Account",command=self.button_add_account_click).grid(row=3,column=0,columnspan=2,pady=2,sticky="ew")
        ctk.CTkButton(self.tab3,text="Launch",command=self.button_launch_game_click).grid(row=4,column=0,columnspan=2,pady=2,sticky="ew")
        ctk.CTkButton(self.tab3,text="Delete Account",command=self.button_delete_account_click).grid(row=5,column=0,columnspan=2,pady=2,sticky="ew")

        self.tab3.columnconfigure(0,weight=1)
        self.tab3.rowconfigure(2,weight=1)

    def open_browser(self,link):
        try: webbrowser.open_new_tab(link)
        except Exception as e: messagebox.showerror("Error",f"cant open browser: {e}")

    def get_toggle_key_from_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path,'r') as f:
                    cfg=json.load(f)
                return cfg.get("bot_toggle_key","")
        except Exception:
            print("read config fail")
        return ""

    def set_toggle_key_in_config(self,new_key):
        try:
            cfg={}
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path,'r') as f: cfg=json.load(f)
                except Exception: pass
            cfg["bot_toggle_key"]=new_key
            with open(self.config_path,'w') as f: json.dump(cfg,f,indent=4)
        except IOError as e:
            messagebox.showerror("Config Error",f"cant save key: {e}")

    def load_initial_settings(self):
        cur=self.get_toggle_key_from_config()
        vals=self.combo_toggle_keys.cget("values")
        if cur and vals and cur in vals: self.selected_toggle_key_var.set(cur)
        elif vals: self.selected_toggle_key_var.set(vals[0])

        bot_vals=self.combo_bot_selection.cget("values")
        if bot_vals: self.selected_bot_var.set(bot_vals[0])

        if os.path.exists(self.rl_txt_path) and os.path.getsize(self.rl_txt_path)>0:
            try:
                with open(self.rl_txt_path,'r') as f:
                    self.rl_directory_var.set(f.read().strip())
            except IOError: pass
        self.refresh_accounts_listbox_and_files()

    def timer_check_injected_tick(self):
        if not psutil:
            self.root.after(10000,self.timer_check_injected_tick)
            return
        active=0
        clean=[]
        for rl_pid,bot_pid in list(self.bot_pids_for_rl.items()):
            if bot_pid:
                try:
                    p=psutil.Process(bot_pid)
                    if p.is_running() and "bot" in p.name().lower():
                        active+=1
                    else: clean.append(rl_pid)
                except psutil.Error: clean.append(rl_pid)
        for rl_pid in clean: del self.bot_pids_for_rl[rl_pid]

        if active:
            self.status_label_var.set(f"{active} Bot{'s' if active>1 else ''} Running")
            self.label_injected_status.configure(text_color="deepskyblue")
        else:
            self.status_label_var.set("Not Running")
            self.label_injected_status.configure(text_color="red")
        self.root.after(10000,self.timer_check_injected_tick)

    def combo_toggle_keys_selected_changed(self, choice: str):
        new=self.selected_toggle_key_var.get()
        if self.get_toggle_key_from_config()!=new:
            self.set_toggle_key_in_config(new)

    def button_find_processes_click(self):
        if not psutil:
            messagebox.showerror("Error","need psutil")
            return
        self.listbox_processes.delete(0,tk.END)
        self.rl_processes_pids_map.clear()
        found=False
        for p in psutil.process_iter(['pid','name']):
            try:
                if "rocketleague" in p.info['name'].lower():
                    txt=str(p.info['pid'])
                    self.listbox_processes.insert(tk.END,txt)
                    self.rl_processes_pids_map[txt]=p.info['pid']
                    found=True
            except psutil.Error: pass
        if not found:
            messagebox.showinfo("Info","no RL processes")

    def get_selected_rl_pid_from_listbox(self):
        sel=self.listbox_processes.curselection()
        if not sel:
            messagebox.showerror("Error","no RL proc selected")
            return None
        pid_txt=self.listbox_processes.get(sel[0])
        try: return int(pid_txt)
        except ValueError:
            messagebox.showerror("Error","bad PID")
            return None

    def _inject_bakkesmod_dll(self,target_pid):
        if platform.system()!="Windows" or not self.dll_injector:
            messagebox.showerror("Error","only windows")
            return False
        try:
            dll=os.path.join(os.getenv('APPDATA'),'bakkesmod','bakkesmod','dll','bakkesmod.dll')
        except Exception as e:
            messagebox.showerror("Path Error",f"cant build dll path: {e}")
            return False
        if not os.path.exists(dll):
            messagebox.showerror("Error",f"dll not found: {dll}")
            return False
        if self.dll_injector.inject_dll(target_pid,dll):
            return True
        messagebox.showerror("Injection Failed",f"inject fail pid {target_pid}")
        return False

    def button_start_bot_click(self):
        target=self.get_selected_rl_pid_from_listbox()
        if target is None: return
        bot=self.selected_bot_var.get()
        if not bot:
            messagebox.showerror("Error","pick bot")
            return

        if target in self.bot_pids_for_rl and self.bot_pids_for_rl[target]:
            try:
                if psutil and psutil.Process(self.bot_pids_for_rl[target]).is_running():
                    messagebox.showinfo("Info","bot already running")
                    return
            except Exception:
                del self.bot_pids_for_rl[target]

        arg=[]
        bot_map={"Nexto":["-b","nexto"],"Necto":["-b","necto"],"Seer (old)":["-b","seer"],
                 "Element":["-b","element"],"NextMortal (air)":["-b","immortal"],
                 "Genesis":["-b","genesis"],"Carbon":["-b","carbon"]}
        b_args=bot_map.get(bot)
        if not b_args:
            messagebox.showerror("Error",f"bad bot {bot}")
            return
        arg.extend(b_args)

        if self.speedflip_var.get(): arg.append("--kickoff")
        if self.bot_minimap_var.get(): arg.append("--minimap")
        if self.bot_monitor_var.get(): arg.append("--monitoring")
        if self.clock_var.get(): arg.append("--clock")
        if self.debugger_var.get(): arg.append("--debug")
        if self.debug_keys_var.get(): arg.append("--debug-keys")

        arg+=["-p",str(target)]

        if self.bakkesmod_var.get() and not self._inject_bakkesmod_dll(target):
            if not messagebox.askyesno("BakkesMod Error","inject failed, continue?"):
                return

        exe="Bot.exe"
        if not os.path.exists(exe) and os.path.exists("Bot.exe.exe"):
            try: os.rename("Bot.exe.exe","Bot.exe")
            except OSError as e:
                messagebox.showerror("File Error",f"rename fail: {e}")
                return
        if not os.path.exists(exe):
            messagebox.showerror("Error","Bot.exe missing")
            return

        try:
            cmd=[os.path.abspath(exe)]+arg
            cwd=os.path.dirname(cmd[0])
            if platform.system()=="Windows":
                proc=subprocess.Popen(cmd,shell=False,cwd=cwd,creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                proc=subprocess.Popen(cmd,shell=False,cwd=cwd)
            self.bot_pids_for_rl[target]=proc.pid
            messagebox.showinfo("Success",f"Bot started pid {proc.pid}")
            self.timer_check_injected_tick()
        except Exception as e:
            messagebox.showerror("Bot Start Error",f"start fail: {e}")

    def button_stop_bot_click(self):
        if not psutil:
            messagebox.showerror("Error","need psutil")
            return
        target=self.get_selected_rl_pid_from_listbox()
        if target is None: return
        bot_pid=self.bot_pids_for_rl.get(target)
        if not bot_pid:
            messagebox.showinfo("Info","no bot tracked")
            return
        try:
            p=psutil.Process(bot_pid)
            if p.is_running() and "bot" in p.name().lower():
                for c in p.children(recursive=True):
                    try: c.terminate()
                    except psutil.Error: pass
                p.terminate()
                try: p.wait(timeout=3)
                except psutil.TimeoutExpired: p.kill()
                messagebox.showinfo("Success","bot killed")
            else:
                messagebox.showinfo("Info","tracked bot not running")
        except psutil.NoSuchProcess:
            messagebox.showinfo("Info","bot already gone")
        except Exception as e:
            messagebox.showerror("Error",f"cant stop bot: {e}")
            if platform.system()=="Windows":
                try:
                    subprocess.run(["taskkill","/F","/T","/PID",str(bot_pid)],
                                   check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    messagebox.showinfo("Success","bot killed via taskkill")
                except Exception as tk_e:
                    messagebox.showerror("Taskkill Error",f"taskkill fail: {tk_e}")
        if target in self.bot_pids_for_rl: del self.bot_pids_for_rl[target]
        self.timer_check_injected_tick()

    def _run_legendary_cli(self,args):
        exe="Legendary.exe"
        if not os.path.exists(exe):
            messagebox.showerror("Error","Legendary.exe missing")
            return None,False
        try:
            inter="auth" in args and not any(a.startswith(("--delete","--code","--sid")) for a in args)
            flags=0
            if platform.system()=="Windows" and not inter:
                flags=subprocess.CREATE_NO_WINDOW
            if inter:
                p=subprocess.Popen([os.path.abspath(exe)]+args,creationflags=0)
                p.wait()
                return "interactive done",p.returncode==0
            cp=subprocess.run([os.path.abspath(exe)]+args,capture_output=True,text=True,check=False,
                              creationflags=flags,encoding='utf-8',errors='replace')
            out=(cp.stdout or "")+(cp.stderr or "")
            return out.strip(),cp.returncode==0
        except FileNotFoundError:
            messagebox.showerror("Error","Legendary.exe missing")
            return None,False
        except Exception as e:
            messagebox.showerror("Legendary Error",f"run fail: {e}")
            return None,False

    def _get_display_name_from_json(self,path):
        try:
            with open(path,'r',encoding='utf-8') as f:
                return json.load(f).get("displayName","Unknown")
        except Exception:
            print(f"read fail {path}")
            return "Error Reading Account"

    def refresh_accounts_listbox_and_files(self):
        self.listbox_usernames.delete(0,tk.END)
        self.legendary_user_accounts_map.clear()
        tmp=[]
        if os.path.exists(self.accounts_dir):
            for n in sorted(os.listdir(self.accounts_dir)):
                if n.lower().endswith(".json"):
                    tmp.append(os.path.join(self.accounts_dir,n))
        idx=1
        processed=set()
        for old in tmp:
            if old in processed: continue
            new=os.path.join(self.accounts_dir,f"Account{idx}.json")
            use=old
            if old!=new:
                try:
                    if os.path.exists(new):
                        if os.path.abspath(old).lower()!=os.path.abspath(new).lower():
                            os.remove(new)
                            os.rename(old,new)
                            use=new
                except OSError as e:
                    print(f"rename err {old}->{new}: {e}")
                    if not os.path.exists(old): continue
            if not os.path.exists(use): continue
            name=self._get_display_name_from_json(use)
            self.listbox_usernames.insert(tk.END,name)
            self.legendary_user_accounts_map[f"{name}_{idx}"]=use
            processed.add(use)
            idx+=1

    def button_select_rl_dir_click(self):
        if self.listbox_usernames.size()==0:
            messagebox.showerror("Error","add account first")
            return
        prev=""
        if os.path.exists(self.rl_txt_path) and os.path.getsize(self.rl_txt_path)>0:
            try:
                with open(self.rl_txt_path,'r') as f: prev=f.read().strip()
            except IOError: pass
        if prev and messagebox.askyesno("Directory Found",f"use {prev}?"):
            self.rl_directory_var.set(prev)
            if not self._import_game_to_legendary():
                self._clear_rl_directory_file()
            return
        folder=filedialog.askdirectory(title="Select RL folder")
        if folder:
            self.rl_directory_var.set(folder)
            try:
                with open(self.rl_txt_path,'w') as f: f.write(folder)
            except IOError as e:
                messagebox.showerror("Error",f"cant save dir: {e}")
                return
            if not self._import_game_to_legendary():
                self._clear_rl_directory_file()

    def _clear_rl_directory_file(self):
        if os.path.exists(self.rl_txt_path):
            try:
                os.remove(self.rl_txt_path)
                self.rl_directory_var.set("")
            except OSError: pass

    def _import_game_to_legendary(self):
        dir_=self.rl_directory_var.get()
        if not dir_:
            messagebox.showerror("Error","dir not set")
            return False
        out,ok=self._run_legendary_cli(["import","Sugar",dir_])
        if out is None: return False
        lo=out.lower()
        if ok and ("already installed" in lo or "has been imported" in lo):
            messagebox.showinfo("Info","Game ready")
            return True
        if "please verify that the path is correct" in lo:
            messagebox.showerror("Import Error","bad dir")
        elif "no saved credentials" in lo:
            messagebox.showerror("Import Error","no account")
        elif "did not find game" in lo or "is not owned by this account" in lo:
            messagebox.showerror("Import Error","not owned")
        elif not ok:
            messagebox.showerror("Legendary Import Error",f"legendary fail\n{out}")
        else:
            messagebox.showwarning("Legendary Output",out)
            return True
        return False

    def _get_legendary_system_config_path(self):
        home=os.path.expanduser("~")
        if platform.system()=="Windows":
            return os.path.join(home,".config","legendary","user.json")
        if platform.system()=="Linux":
            return os.path.join(home,".config","legendary","user.json")
        if platform.system()=="Darwin":
            return os.path.join(home,"Library","Application Support","legendary","user.json")
        return os.path.join(home,".config","legendary","user.json")

    # ---------- NEW: helper to compare mtimes safely ----------
    def _is_newer(self, src_path, dst_path):
        try:
            if not os.path.exists(src_path):
                return False
            if not os.path.exists(dst_path):
                return True
            return os.path.getmtime(src_path) > os.path.getmtime(dst_path)
        except Exception:
            return True
    # ----------------------------------------------------------

    def button_add_account_click(self):
        self._run_legendary_cli(["auth","--delete"])
        messagebox.showinfo("Legendary","Legendary auth now")
        out,ok=self._run_legendary_cli(["auth"])
        if out is None: return
        if not ok:
            if "Max retries" in out:
                messagebox.showerror("Auth Failed","rate limit")
            elif "Login failed" in out:
                messagebox.showerror("Auth Failed","login failed")
            else:
                messagebox.showerror("Auth Failed","auth fail")
            return
        sys_cfg=self._get_legendary_system_config_path()
        if not sys_cfg or not os.path.exists(sys_cfg):
            messagebox.showerror("Auth Error","user.json missing")
            return
        idxs=[]
        if os.path.exists(self.accounts_dir):
            for f in os.listdir(self.accounts_dir):
                m=re.match(r"Account(\d+)\.json",f,re.I)
                if m: idxs.append(int(m.group(1)))
        new_idx=max(idxs)+1 if idxs else 1
        new_path=os.path.join(self.accounts_dir,f"Account{new_idx}.json")
        try:
            shutil.copy2(sys_cfg,new_path)
            name=self._get_display_name_from_json(sys_cfg)
            messagebox.showinfo("Success",f"Account '{name}' added")
            self.refresh_accounts_listbox_and_files()
        except Exception as e:
            messagebox.showerror("File Error",f"save fail: {e}")

    def _get_account_path_from_selection(self):
        sel=self.listbox_usernames.curselection()
        if not sel: return None,None
        idx=sel[0]
        name=self.listbox_usernames.get(idx)
        path=os.path.join(self.accounts_dir,f"Account{idx+1}.json")
        if not os.path.exists(path):
            found=None
            for k,v in self.legendary_user_accounts_map.items():
                if name in k and os.path.basename(v)==f"Account{idx+1}.json":
                    found=v
                    break
            if found and os.path.exists(found):
                path=found
            else:
                messagebox.showerror("Internal Error","cant find file")
                return None,None
        return path,name

    def button_launch_game_click(self):
        # Token-safe: only push account -> sys when needed, then copy back sys -> account after launch
        path,name=self._get_account_path_from_selection()
        if not path:
            messagebox.showerror("Error","no account selected")
            return
        sys_cfg=self._get_legendary_system_config_path()
        if not sys_cfg:
            messagebox.showerror("Error","config path err")
            return

        # Ensure cfg dir exists
        try:
            os.makedirs(os.path.dirname(sys_cfg),exist_ok=True)
        except Exception as e:
            messagebox.showerror("File Error",f"cfg dir fail: {e}")
            return

        # ---- PUSH: only if account file is newer or sys_cfg missing ----
        try:
            if self._is_newer(path, sys_cfg):
                shutil.copy2(path, sys_cfg)
        except Exception as e:
            messagebox.showerror("File Error",f"copy to system cfg fail: {e}")
            return

        active=self._get_display_name_from_json(sys_cfg)
        if "Error" in active: active=name or "Account"
        messagebox.showinfo("Launching",f"Launching RL for {active}")

        out,ok=self._run_legendary_cli(["launch","Sugar","--skip-version-check"])
        if out is None: 
            # Even if None, attempt to pull back creds if present
            try:
                if os.path.exists(sys_cfg) and self._is_newer(sys_cfg, path):
                    shutil.copy2(sys_cfg, path)
            except Exception as e:
                messagebox.showwarning("Token persist warning",f"Couldn't update account file: {e}")
            return

        # ---- PULL BACK: keep rotated token in per-account file ----
        try:
            if os.path.exists(sys_cfg) and self._is_newer(sys_cfg, path):
                shutil.copy2(sys_cfg, path)
        except Exception as e:
            messagebox.showwarning("Token persist warning",f"Couldn't update account file: {e}")

        if not ok:
            lo=out.lower()
            if "no saved credentials" in lo:
                messagebox.showerror("Launch Error","no creds")
            elif "are no longer valid" in lo or "invalid_token" in lo:
                messagebox.showerror("Launch Error","token invalid")
            elif "is not installed" in lo:
                messagebox.showerror("Launch Error","game not imported")
            else:
                messagebox.showwarning("Legendary Launch",out)

    def button_delete_account_click(self):
        path,name=self._get_account_path_from_selection()
        if not path:
            messagebox.showerror("Error","no account selected")
            return
        if messagebox.askyesno("Confirm",f"delete '{name}'?"):
            try:
                os.remove(path)
                messagebox.showinfo("Success","account deleted")
                self.refresh_accounts_listbox_and_files()
            except OSError as e:
                messagebox.showerror("Error",f"delete fail: {e}")

if __name__=="__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    if platform.system()=="Windows" and KERNEL32 is None:
        messagebox.showerror("Startup Error","Kernel32 fail")

    if not psutil:
        messagebox.showwarning("Dependency","psutil missing features limited")

    main_root=ctk.CTk()
    app=RLOrbitalApp(main_root)
    main_root.mainloop()
