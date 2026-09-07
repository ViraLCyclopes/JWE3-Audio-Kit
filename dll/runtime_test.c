// Offline harness. Never loads JWE3.exe or calls its Wwise API.
#include "VLXInput.c"
static int calls;
static unsigned char fake_ready(void) { return 1; }
static int fake_load(const void* data, unsigned int size, unsigned int* bank) {
    if (!vl_bank_header((const unsigned char*)data,size,bank)) return 2;
    calls++;
    return 1;
}
int wmain(int argc, wchar_t** argv) {
    if (argc != 2) { fprintf(stderr,"usage: runtime_test GAME_FIXTURE_ROOT\n"); return 2; }
    if (!InitOnceExecuteOnce(&vl_paths_once,vl_paths,NULL,NULL)) return 2;
    if (wcscpy_s(vl_root,VL_PATH,argv[1])) return 2;
    if (!metadata_read(L"C:/Games/JWE3/Win64/ovldata/content0/audio/metadata/audiometadata.ovl",GENERIC_READ,OPEN_EXISTING)) return 3;
    if (metadata_read(L"C:/Unrelated/audiometadata.ovl",GENERIC_READ,OPEN_EXISTING)) return 4;
    if (metadata_read(L"Content0/Audio/MetaData/audiometadata.ovl",GENERIC_WRITE,OPEN_EXISTING)) return 5;
    audio_opened(L"test_media.ovl",INVALID_HANDLE_VALUE,OPEN_EXISTING);
    if (vl_audio_seen) return 6;
    audio_opened(L"TEST_MEDIA.OVL",(HANDLE)(ULONG_PTR)1,OPEN_EXISTING);
    if (!vl_audio_seen) return 7;
    if (!vl_prepare()) return 1;
    vl_load_banks(fake_load,fake_ready,0);
    printf("fake_load_calls=%d\n",calls);
    return 0;
}
