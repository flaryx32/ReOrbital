import ctypes
from ctypes import wintypes
import platform

# only runs ok on windows, bail otherwise
if platform.system()!="Windows":
    pass

# load kernel32 if we can
KERNEL32=ctypes.WinDLL('kernel32',use_last_error=True) if platform.system()=="Windows" else None

# proc rights (winnt.h bits we care about)
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

# mem flags
MEM_COMMIT=0x1000
MEM_RESERVE=0x2000
MEM_COMMIT_RESERVE=MEM_COMMIT|MEM_RESERVE

# page prot
PAGE_EXECUTE_READWRITE=0x40

# wire up signatures only when kernel32 exists
if KERNEL32:
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
            raise OSError("dll inject only on windows")
        self.desired_access=PROCESS_ALL_ACCESS_CUSTOM
        self.allocation_type=MEM_COMMIT_RESERVE
        self.protection=PAGE_EXECUTE_READWRITE

    def inject_dll(self,process_id:int,dll_path:str)->bool:
        process_handle=KERNEL32.OpenProcess(self.desired_access,True,process_id)
        if not process_handle or process_handle==INTPTR_ZERO:
            print(f"cant open pid {process_id}. err {ctypes.get_last_error()}")
            return False
        try:
            kernel32_handle=KERNEL32.GetModuleHandleA(b"kernel32.dll")
            if not kernel32_handle or kernel32_handle==INTPTR_ZERO:
                print(f"no kernel32 handle. err {ctypes.get_last_error()}")
                return False
            load_library_addr=KERNEL32.GetProcAddress(kernel32_handle,b"LoadLibraryA")
            if not load_library_addr or load_library_addr==INTPTR_ZERO:
                print(f"cant find LoadLibraryA. err {ctypes.get_last_error()}")
                return False
            dll_bytes=dll_path.encode('ascii')
            c_buf=ctypes.create_string_buffer(dll_bytes)
            size_to_alloc=ctypes.sizeof(c_buf)
            arg_address=KERNEL32.VirtualAllocEx(process_handle,None,size_to_alloc,
                                               self.allocation_type,self.protection)
            if not arg_address or arg_address==INTPTR_ZERO:
                print(f"remote alloc fail. err {ctypes.get_last_error()}")
                return False
            try:
                bytes_written=ctypes.c_size_t(0)
                ok=KERNEL32.WriteProcessMemory(process_handle,arg_address,c_buf,
                                               size_to_alloc,ctypes.byref(bytes_written))
                if not ok:
                    print(f"write mem fail. err {ctypes.get_last_error()}")
                    return False
                thread_id=wintypes.DWORD(0)
                remote_thread_handle=KERNEL32.CreateRemoteThread(process_handle,None,0,
                                                                 load_library_addr,arg_address,0,
                                                                 ctypes.byref(thread_id))
                if not remote_thread_handle or remote_thread_handle==INTPTR_ZERO:
                    print(f"remote thread fail. err {ctypes.get_last_error()}")
                    return False
                KERNEL32.CloseHandle(remote_thread_handle)
                return True
            finally:
                pass   # todo: free mem maybe if issues (pls don't forget this if i ever get issues)
        finally:
            KERNEL32.CloseHandle(process_handle)
