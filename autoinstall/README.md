# Auto Install

Guides to build a custom linux distros like (Ubuntu Desktop)
bootable ISO with an embedded `ubuntu.yaml` configuration. The default working directory `~/ubuntu-autoinstall` is default as it is more convenient when testing, but feel free to modify as it is needed. Currently the `build.sh` support only Ubuntu base.. but I am commited to support as manay as possible distros.

Target ISO:

- ubuntu-24.04.4-desktop-amd64.iso
- ubuntu-25.10-desktop-amd64.iso

Method:

- Preserves BIOS boot
- Preserves UEFI boot
- Preserves hybrid GPT/MBR layout
- Maintains Secure Boot compatibility
- Avoids modifying a live USB directly
- Uses xorriso to replay original boot metadata

> Boxes,
Virtual machine manager,
Chrome,
Remmina Remote desktop client,
DBeaver Community,
DB Browser for SQLite,
Inkscape,
GIMP,
Audacity,
VS Code

## Password

```bash
openssl passwd -6 "abc"
$6$mTP2GjN.z.TutOT4$Td1sJhOmqpzSX.0lDIZ1hNDcYVWE1Hcf.GX2oXLXsqFZkFI1obt0SEB8.s9OueeNGkSadAt2InCUvPiE7s0P8/
```

---

## Requirements

Install required tool:

```bash
sudo apt install xorriso
```

Needed:

- Original Ubuntu Desktop ISO
- rsync
- openssl (for password hashing)

## 1. Create Clean Working Directory

```bash
rm -rf ~/ubuntu-autoinstall
mkdir -p ~/ubuntu-autoinstall/{mnt,extract}
```

## 2. Mount Original ISO

```bash
sudo mount /mnt/keep/os/linux/Ubuntu/ubuntu-24.04.4-desktop-amd64.iso \
    ~/ubuntu-autoinstall/mnt
```

(Note: ISO mounts read-only. This is expected.)

## 3. Copy ISO Contents

```bash
rsync -a ~/ubuntu-autoinstall/mnt/ \
    ~/ubuntu-autoinstall/extract/

sudo umount ~/ubuntu-autoinstall/mnt
```

Now the `extract/` directory is writable.

## 4. Add Autoinstall Configuration

Create directory and files:

```bash
sudo mkdir ~/ubuntu-autoinstall/extract/nocloud

# Create user-data, get content from ubuntu.yaml
sudo nano ~/ubuntu-autoinstall/extract/nocloud/user-data

#  Create meta-data 
sudo nano ~/ubuntu-autoinstall/extract/nocloud/meta-data
# Content:
#     instance-id: desktop-autoinstall
```

## 5. Modify GRUB Configuration

Edit:

```bash
nano ~/ubuntu-autoinstall/extract/boot/grub/grub.cfg

# Find:
linux   /casper/vmlinuz quiet splash ---
linux   /casper/vmlinuz  --- quiet splash

# Replace with:
linux   /casper/vmlinuz quiet splash autoinstall ds=nocloud\;s=/cdrom/nocloud/ ---
linux   /casper/vmlinuz  autoinstall ds=nocloud\;s=/cdrom/nocloud/ --- quiet splash

menuentry "Try or Install Ubuntu" {
        set gfxpayload=keep
        linux   /casper/vmlinuz  --- quiet splash
        initrd  /casper/initrd
}
menuentry "Ubuntu Autoinstall (Wipes Disk)" {
        set gfxpayload=keep
        linux   /casper/vmlinuz  autoinstall ds=nocloud\;s=/cdrom/nocloud/ --- quiet splash
        initrd  /casper/initrd
}
```

Important:

- Keep the final `---`
- Escape semicolon as `\;`
- Do not remove other parameters

> The `---` is a separator.
Everything before `---` goes to the kernel.
Everything after `---` goes to the installer (subiquity).

Ubuntu Desktop ISOs sometimes flip order depending on build.

## 6. Rebuild ISO (Safe Patch Method)

```bash
cd ~/ubuntu-autoinstall

xorriso \
  -indev /path/to/ubuntu-24.04.4-desktop-amd64.iso \
  -outdev ubuntu-24.04.4-desktop-autoinstall.iso \
  -boot_image any replay \
  -map extract/nocloud /nocloud \
  -map extract/boot/grub/grub.cfg /boot/grub/grub.cfg
```

This preserves original boot structure and replaces only modified files.

## 7. Verify Boot Structure

```bash
xorriso -indev ubuntu-24.04.4-desktop-autoinstall.iso \
-report_el_torito plain
```

Expected output includes:

- BIOS boot image
- UEFI boot image
- "MBR protective-msdos-label grub2-mbr"
- GPT present

## 8. Verify Autoinstall Files

```bash
xorriso -indev ubuntu-24.04.4-desktop-autoinstall.iso -ls /nocloud
```

Expected:

```bash
user-data
meta-data
```

## 9. Flash to USB

Use GNOME Disks:

Restore Disk Image → select ubuntu-24.04.4-desktop-autoinstall.iso

Do NOT:

- Format USB manually
- Create partitions manually
- Use ISO mode in Rufus

Write the ISO as a raw image.

## Expected Boot Behavior

On boot:

- GRUB loads normally
- Installer starts automatically
- No interactive setup wizard
- Installation begins immediately

WARNING:
If using `storage: layout: direct`, the target disk will be wiped immediately.

Test in a VM before using on production hardware.

## Notes

This method avoids:

- CIDATA partition hacks
- Editing a live USB
- Rebuilding El Torito structures manually
- Breaking UEFI compatibility

Boot metadata is replayed directly from the original ISO using xorriso.
