// Production xinput1_4 proxy, version 6.1. Registry/bank validation is shared
// with VLAudioLoader.c. XInput ordinals match the current JWE3 executable.
#include "VLAudioRuntime.h"
#define VL_STACK_SAFE_HOOKS 1

static INIT_ONCE real_once = INIT_ONCE_STATIC_INIT;
static HMODULE real_xinput;
static HANDLE prepared;
static wchar_t registry_target[VL_PATH]; // immutable after prepared is signaled
typedef HANDLE (WINAPI *CreateW)(LPCWSTR,DWORD,DWORD,LPSECURITY_ATTRIBUTES,DWORD,DWORD,HANDLE);
typedef HANDLE (WINAPI *Create2)(LPCWSTR,DWORD,DWORD,DWORD,LPCREATEFILE2_EXTENDED_PARAMETERS);
static CreateW real_create_w;
static Create2 real_create_2;
static volatile LONG redirect_logs;
static volatile LONG proxy_complete;

static BOOL CALLBACK init_real(PINIT_ONCE once, PVOID arg, PVOID* ctx) {
    wchar_t path[MAX_PATH];
    UINT n;
    (void)once; (void)arg; (void)ctx;
    n = GetSystemDirectoryW(path, MAX_PATH);
    if (!n || n >= MAX_PATH - 20) return FALSE;
    wcscat_s(path, MAX_PATH, L"\\xinput1_4.dll");
    real_xinput = LoadLibraryW(path);
    return real_xinput != NULL;
}
static FARPROC real_proc(const char* name) {
    if (!InitOnceExecuteOnce(&real_once, init_real, NULL, NULL)) return NULL;
    return GetProcAddress(real_xinput, name);
}
__declspec(dllexport) DWORD WINAPI XInputGetState(DWORD id, void* state) {
    typedef DWORD (WINAPI *Fn)(DWORD,void*);
    Fn fn = (Fn)real_proc("XInputGetState");
    return fn ? fn(id,state) : ERROR_DEVICE_NOT_CONNECTED;
}
__declspec(dllexport) DWORD WINAPI XInputGetCapabilities(DWORD id, DWORD flags, void* caps) {
    typedef DWORD (WINAPI *Fn)(DWORD,DWORD,void*);
    Fn fn = (Fn)real_proc("XInputGetCapabilities");
    return fn ? fn(id,flags,caps) : ERROR_DEVICE_NOT_CONNECTED;
}
__declspec(dllexport) DWORD WINAPI XInputGetKeystroke(DWORD id, DWORD flags, void* key) {
    typedef DWORD (WINAPI *Fn)(DWORD,DWORD,void*);
    Fn fn = (Fn)real_proc("XInputGetKeystroke");
    return fn ? fn(id,flags,key) : ERROR_DEVICE_NOT_CONNECTED;
}

static const wchar_t* basename_w(const wchar_t* p) {
    const wchar_t *a, *b;
    if (!p) return L"";
    a = wcsrchr(p,L'\\'); b = wcsrchr(p,L'/');
    if (b && (!a || b > a)) a = b;
    return a ? a + 1 : p;
}
static int metadata_read(LPCWSTR p, DWORD access, DWORD disposition) {
    // This shared component owns only the registry override. Raw mod banks are
    // explicitly loaded. It must not hijack unrelated OVLs by basename.
    size_t n;
    const wchar_t* tail = L"win64/ovldata/content0/audio/metadata/audiometadata.ovl";
    const wchar_t* alternatives[] = {tail, L"ovldata/content0/audio/metadata/audiometadata.ovl", L"content0/audio/metadata/audiometadata.ovl"};
    size_t option;
    if (!p || disposition != OPEN_EXISTING || (access & (GENERIC_WRITE|DELETE|FILE_WRITE_DATA))) return 0;
    n = wcslen(p);
    if (n >= VL_PATH) return 0;
    for (option = 0; option < 3; option++) {
        size_t length = wcslen(alternatives[option]), i;
        const wchar_t* candidate;
        if (n < length || (option != 0 && n != length)) continue;
        candidate = p + n - length;
        if (candidate != p && candidate[-1] != L'/' && candidate[-1] != L'\\') continue;
        for (i = 0; i < length; i++) {
            wchar_t c = candidate[i];
            if (c == L'\\') c = L'/';
            if (c >= L'A' && c <= L'Z') c += L'a' - L'A';
            if (c != alternatives[option][i]) break;
        }
        if (i == length) return 1;
    }
    return 0;
}
static void audio_opened(LPCWSTR p, HANDLE file, DWORD disposition) {
    const wchar_t* name = basename_w(p);
    // Observe only successful opens of audio payloads, on either API.
    if (file != INVALID_HANDLE_VALUE && disposition == OPEN_EXISTING &&
        (vl_suffix(name,L"_bnk_b.aux") || vl_suffix(name,L"_media.ovl") || vl_suffix(name,L"_events.ovl") || vl_suffix(name,L".bnk")))
        InterlockedExchange(&vl_audio_seen,1);
}
static int redirect_ready(LPCWSTR p, DWORD access, DWORD disposition) {
    DWORD error = GetLastError();
    int ok = 0;
    if (metadata_read(p,access,disposition)) {
        // Installer patches imports before hashing inputs so the game cannot read
        // the old registry while validation is in progress.
        if (WaitForSingleObject(prepared,30000) == WAIT_OBJECT_0 && vl_valid)
            ok = registry_target[0] != 0;
    }
    SetLastError(error);
    return ok;
}
static HANDLE WINAPI hook_w(LPCWSTR p,DWORD a,DWORD s,LPSECURITY_ATTRIBUTES sa,DWORD c,DWORD f,HANDLE t) {
    HANDLE h;
    DWORD error;
    if (redirect_ready(p,a,c)) {
        h = real_create_w(registry_target,a,s,sa,c,f,t);
        if (h != INVALID_HANDLE_VALUE) {
            error = GetLastError();
            if (InterlockedIncrement(&redirect_logs) <= 20) vlog("Registry redirect: %ls",registry_target);
            SetLastError(error); return h;
        }
        vlog("Registry redirect failed; falling back to stock (error %lu)",GetLastError());
    }
    h = real_create_w(p,a,s,sa,c,f,t);
    error = GetLastError(); audio_opened(p,h,c); SetLastError(error);
    return h;
}
static HANDLE WINAPI hook_2(LPCWSTR p,DWORD a,DWORD s,DWORD c,LPCREATEFILE2_EXTENDED_PARAMETERS ex) {
    HANDLE h;
    DWORD error;
    if (redirect_ready(p,a,c)) {
        h = real_create_2(registry_target,a,s,c,ex);
        if (h != INVALID_HANDLE_VALUE) return h;
        vlog("Registry redirect failed; falling back to stock (error %lu)",GetLastError());
    }
    h = real_create_2(p,a,s,c,ex);
    error = GetLastError(); audio_opened(p,h,c); SetLastError(error);
    return h;
}
static int patch_iat(HMODULE module,const char* name,void* replacement,void** original) {
    BYTE* base = (BYTE*)module;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    IMAGE_NT_HEADERS* nt;
    IMAGE_IMPORT_DESCRIPTOR* imports;
    DWORD rva;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    nt = (IMAGE_NT_HEADERS*)(base+dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
    rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return 0;
    imports = (IMAGE_IMPORT_DESCRIPTOR*)(base+rva);
    for (; imports->Name; imports++) {
        IMAGE_THUNK_DATA *names, *slots;
        const char* dll = (const char*)(base+imports->Name);
        if (_stricmp(dll,"kernel32.dll") && _stricmp(dll,"kernelbase.dll") &&
            _strnicmp(dll,"api-ms-win-core-file-",21)) continue;
        // When OFT is absent FirstThunk already contains function pointers,
        // not name RVAs. Never interpret resolved addresses as PE offsets.
        if (!imports->OriginalFirstThunk) continue;
        names = (IMAGE_THUNK_DATA*)(base+imports->OriginalFirstThunk);
        slots = (IMAGE_THUNK_DATA*)(base+imports->FirstThunk);
        for (; names->u1.AddressOfData; names++,slots++) {
            IMAGE_IMPORT_BY_NAME* fn;
            DWORD protect;
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            fn = (IMAGE_IMPORT_BY_NAME*)(base+names->u1.AddressOfData);
            if (strcmp((const char*)fn->Name,name)) continue;
            if (!VirtualProtect(&slots->u1.Function,sizeof(void*),PAGE_READWRITE,&protect)) return 0;
            *original = (void*)slots->u1.Function;
            MemoryBarrier();
            InterlockedExchangePointer((PVOID volatile*)&slots->u1.Function,replacement);
            VirtualProtect(&slots->u1.Function,sizeof(void*),protect,&protect);
            return 1;
        }
    }
    return 0;
}
static DWORD WINAPI install(LPVOID arg) {
    HMODULE exe = GetModuleHandleW(NULL), self;
    int w, two;
    (void)arg;
    // Hooks and worker reference this DLL for process lifetime.
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                       (LPCWSTR)&install,&self);
    prepared = CreateEventW(NULL,TRUE,FALSE,NULL);
    if (!prepared) return 0;
    w = patch_iat(exe,"CreateFileW",(void*)hook_w,(void**)&real_create_w);
    two = patch_iat(exe,"CreateFile2",(void*)hook_2,(void**)&real_create_2);
    vlog("=== VLAudioLoader v6.1; hooks CreateFileW=%d CreateFile2=%d ===",w,two);
    if ((w || two) && vl_data_path(registry_target,L"VLAudioLoader/Audio/audiometadata.ovl")) vl_prepare();
    SetEvent(prepared);
    if (vl_valid) vl_load_all(1);
    InterlockedExchange(&proxy_complete,1);
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        HANDLE thread;
        DisableThreadLibraryCalls(instance);
        thread = CreateThread(NULL,1024*1024,install,NULL,STACK_SIZE_PARAM_IS_A_RESERVATION,NULL);
        if (thread) CloseHandle(thread);
    }
    return TRUE;
}
