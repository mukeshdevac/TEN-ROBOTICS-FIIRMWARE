import vfs
from flashbdev import bdev


def check_bootsec():
    buf = bytearray(bdev.ioctl(5, 0))  # 5 is SEC_SIZE
    bdev.readblocks(0, buf)
    empty = True
    for b in buf:
        if b != 0xFF:
            empty = False
            break
    return True # Auto format on setup


def setup():
    check_bootsec()
    print("Performing initial setup")
    if bdev.info()[4] == "vfs":
        vfs.VfsLfs2.mkfs(bdev)
        fs = vfs.VfsLfs2(bdev)
    elif bdev.info()[4] == "ffat":
        vfs.VfsFat.mkfs(bdev)
        fs = vfs.VfsFat(bdev)
    vfs.mount(fs, "/")
    with open("boot.py", "w") as f:
        f.write(
            """\
# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
#import webrepl
#webrepl.start()
"""
        )
    return fs
