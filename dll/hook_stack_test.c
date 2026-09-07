// Regression for the 2026-09-06 startup dump: exercise the REAL hook functions
// on a 64 KiB fiber stack. No game process or real Wwise functions are involved.
#include "VLXInput.c"
static void* caller_fiber;
static int failures, calls;
static HANDLE WINAPI fake_w(LPCWSTR p,DWORD a,DWORD s,LPSECURITY_ATTRIBUTES sa,DWORD c,DWORD f,HANDLE t) {
    (void)p;(void)a;(void)s;(void)sa;(void)c;(void)f;(void)t;
    calls++;
    SetLastError(1234);
    return (HANDLE)(ULONG_PTR)42;
}
static HANDLE WINAPI fake_2(LPCWSTR p,DWORD a,DWORD s,DWORD c,LPCREATEFILE2_EXTENDED_PARAMETERS ex) {
    (void)ex;
    return fake_w(p,a,s,NULL,c,0,NULL);
}
static VOID WINAPI small_stack(LPVOID arg) {
    int i;
    HANDLE h;
    (void)arg;
    for (i=0;i<100;i++) {
        h=hook_w(L"C:/unrelated/file.txt",GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
        if (h!=(HANDLE)(ULONG_PTR)42 || GetLastError()!=1234) failures++;
        h=hook_2(L"Content0/Audio/MetaData/audiometadata.ovl",GENERIC_READ,FILE_SHARE_READ,OPEN_EXISTING,NULL);
        if (h!=(HANDLE)(ULONG_PTR)42 || GetLastError()!=1234) failures++;
    }
    SwitchToFiber(caller_fiber);
}
int main(void) {
    void* fiber;
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
    InitOnceExecuteOnce(&vl_paths_once,vl_paths,NULL,NULL);
    real_create_w=fake_w;
    real_create_2=fake_2;
    prepared=CreateEventW(NULL,TRUE,TRUE,NULL);
#ifdef VL_STACK_SAFE_HOOKS
    vl_data_path(registry_target,L"VLAudioLoader/Audio/audiometadata.ovl");
#endif
    vl_valid=1;
    caller_fiber=ConvertThreadToFiber(NULL);
    fiber=CreateFiberEx(4096,65536,0,small_stack,NULL);
    if (!prepared || !caller_fiber || !fiber) return 2;
    SwitchToFiber(fiber);
    DeleteFiber(fiber);
    ConvertFiberToThread();
    CloseHandle(prepared);
    printf("64 KiB stack: %d hook calls, %d failures\n",calls,failures);
    return failures || calls!=200;
}
