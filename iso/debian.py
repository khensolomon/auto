#!/usr/bin/env python3

"""
Debian Automated ISO Builder
Translates the full interactive flow of debian.sh into a clean Python script.
"""

import os
import sys
import core
import shutil
import argparse

DEPENDENCIES = ['xorriso', 'rsync', 'openssl']
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

def generate_preseed(config, user_inputs):
    data = config.get('autoinstall', {})
    
    hostname = user_inputs['hostname']
    username = user_inputs['username']
    realname = user_inputs['realname']
    password = user_inputs['password_hash'] or data.get('password')
    timezone = user_inputs['timezone']
    disk_layout = user_inputs['disk_layout']
    crypto_pass = user_inputs['crypto_pass']
    
    # Safely pull locale and keyboard from prompts, falling back to YAML
    locale = user_inputs.get('locale', data.get('locale', 'en_US.UTF-8'))
    keyboard = user_inputs.get('layout', data.get('keyboard', 'us'))
    kybd_variant = user_inputs.get('variant', '')
    kybd_toggle = user_inputs.get('toggle', '')
    
    packages = data.get('packages', [])
    snaps = data.get('snaps', [])
    if snaps and 'snapd' not in packages:
        packages.append('snapd')
        
    tasksel_tasks = []
    if 'standard' in packages:
        packages.remove('standard')
        tasksel_tasks.append('standard')
        
    tasksel_str = ", ".join(tasksel_tasks) if tasksel_tasks else ""
    packages_str = " ".join(packages)

    preseed = f"""# ==========================================
# AUTO-GENERATED DEBIAN PRESEED
# ==========================================
d-i debian-installer/locale string {locale}
d-i keyboard-configuration/xkb-keymap select {keyboard}
d-i netcfg/get_hostname string {hostname}
d-i netcfg/get_domain string unassigned-domain
d-i mirror/country string manual
d-i mirror/http/hostname string deb.debian.org
d-i mirror/http/directory string /debian
d-i mirror/http/proxy string
d-i passwd/root-login boolean false
d-i passwd/user-fullname string {realname}
d-i passwd/username string {username}
d-i passwd/user-password-crypted password {password}
d-i clock-setup/utc boolean true
d-i time/zone string {timezone}
"""

    if kybd_variant:
        preseed += f"d-i keyboard-configuration/variant string {kybd_variant}\n"
    if kybd_toggle:
        preseed += f"d-i keyboard-configuration/optionscode string {kybd_toggle}\n"

    if disk_layout == 0:  # Standard
        preseed += """d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
"""
    elif disk_layout == 1: # LVM
        preseed += """d-i partman-auto/method string lvm
d-i partman-lvm/device_remove_lvm boolean true
d-i partman-md/device_remove_md boolean true
d-i partman-lvm/confirm boolean true
d-i partman-lvm/confirm_nooverwrite boolean true
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
"""
    elif disk_layout == 2: # LUKS
        preseed += f"""d-i partman-auto/method string crypto
d-i partman-lvm/device_remove_lvm boolean true
d-i partman-md/device_remove_md boolean true
d-i partman-lvm/confirm boolean true
d-i partman-lvm/confirm_nooverwrite boolean true
d-i partman-auto-crypto/erase_data boolean false
d-i partman-crypto/passphrase password {crypto_pass}
d-i partman-crypto/passphrase-again password {crypto_pass}
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
"""

    preseed += f"""
tasksel tasksel/first multiselect {tasksel_str}
d-i pkgsel/include string {packages_str}
d-i pkgsel/upgrade select full-upgrade
popularity-contest popularity-contest/participate boolean false
d-i grub-installer/only_debian boolean true
d-i grub-installer/with_other_os boolean true
d-i grub-installer/bootdev  string default
d-i preseed/late_command string \\
  echo '#!/bin/bash' > /target/root/post_install.sh; \\
"""

    if snaps:
        preseed += "  echo 'systemctl start snapd' >> /target/root/post_install.sh; \\\n"
        for snap in snaps:
            name = snap.get('name')
            classic = "--classic" if snap.get('classic') else ""
            preseed += f"  echo 'snap install {name} {classic}' >> /target/root/post_install.sh; \\\n"

    for cmd in data.get('late_cmds', []):
        clean_cmd = cmd.replace('curtin in-target -- ', '').replace("'", "'\\''") 
        preseed += f"  echo '{clean_cmd}' >> /target/root/post_install.sh; \\\n"

    preseed += "  in-target chmod +x /root/post_install.sh; \\\n"
    preseed += "  in-target /bin/bash /root/post_install.sh; \\\n"
    preseed += "  in-target rm /root/post_install.sh\n"
    preseed += "\nd-i finish-install/reboot_in_progress note\n"

    return preseed

def main():
    parser = argparse.ArgumentParser(description="Debian Autoinstall ISO Builder")
    parser.add_argument('--dry-run', action='store_true', help="Generate configs only, skip ISO build")
    parser.add_argument('--unattended', action='store_true', help="Skip all prompts and use defaults")
    args = parser.parse_args()

    if args.unattended:
        core.UNATTENDED = True

    core.print_header("Step 1: Debian Builder Setup")
    if not args.dry_run:
        core.check_dependencies(DEPENDENCIES)

    work_dir = core.setup_work_dir("~/debian-autoinstall")
    
    default_yaml = os.path.join(SCRIPT_DIR, "autoinstall.yaml")
    yaml_path = core.ask_input("Enter autoinstall.yaml path", default_yaml)
    yaml_path = os.path.expanduser(yaml_path)

    if not os.path.exists(yaml_path):
        core.print_error(f"Configuration file not found at '{yaml_path}'.")

    if not args.dry_run:
        iso_path = core.ask_iso_path(os_hint="Debian")
        iso_path = os.path.expanduser(iso_path)

        if not os.path.exists(iso_path):
            core.print_error(f"Source ISO not found at '{iso_path}'.")
    else:
        core.print_info("Dry-Run enabled. Skipping ISO preparation.")

    core.print_info("Extracting data from YAML...")
    config = core.parse_simple_yaml(yaml_path)
    data = config.get('autoinstall', {})

    # Auto-detect Host system defaults
    host_tz = core.get_host_timezone()
    host_locale = core.get_host_locale()
    host_kb = core.get_host_keyboard()

    # Prioritize Host OS -> YAML -> Hardcoded
    def_locale = host_locale or data.get('locale', 'en_US.UTF-8')
    def_layout = host_kb['layout'] or data.get('keyboard', 'us')
    def_variant = host_kb['variant'] or data.get('keyboard_variant', '')
    def_toggle = host_kb['toggle'] or data.get('keyboard_toggle', '')

    new_host = core.ask_input("Enter Target Hostname", data.get('hostname', 'debian-mini'))
    new_timezone = core.ask_input(f"Enter Timezone (Host: {host_tz})", data.get('timezone', host_tz))
    
    loc_hint = f"Host: {host_locale}" if host_locale else "e.g., en_US.UTF-8"
    new_locale = core.ask_input(f"Enter System Locale ({loc_hint})", def_locale)
    
    lyt_hint = f"Host: {host_kb['layout']}" if host_kb['layout'] else "e.g., us, no"
    kybd_layout = core.ask_input(f"Enter Keyboard Layout ({lyt_hint})", def_layout)
    
    var_hint = f"Host: {host_kb['variant']}" if host_kb['variant'] else "leave blank for none"
    kybd_variant = core.ask_input(f"Enter Keyboard Variant ({var_hint})", def_variant)
    
    tgl_hint = f"Host: {host_kb['toggle']}" if host_kb['toggle'] else "e.g., grp:alt_shift_toggle"
    kybd_toggle = core.ask_input(f"Enter Keyboard Toggle ({tgl_hint})", def_toggle)

    new_user = core.ask_input("Enter Target Username", data.get('username', 'user'))
    new_realname = core.ask_input("Enter Target Real Name", data.get('realname', 'User'))
    
    plain_password = core.ask_password("Enter Password (blank to keep template hash)")
    password_hash = core.hash_password(plain_password) if plain_password else None

    if not core.UNATTENDED: print()
    disk_layout = core.ask_choice("Select Disk Partitioning", ["Standard (Direct Wipe)", "LVM (Logical Volume Manager)", "Encrypted LVM (LUKS)"], default=1)
    crypto_pass = ""
    if disk_layout == 2:
        crypto_pass = core.ask_password("Enter Master LUKS Encryption Password")
        if not crypto_pass:
            core.print_error("A password is required for LUKS encryption.")

    config = core.run_os_prompts(config, 'debian')
    config = core.merge_os_overrides(config, os_name='debian')

    user_inputs = {
        'hostname': new_host,
        'timezone': new_timezone,
        'locale': new_locale,
        'layout': kybd_layout,
        'variant': kybd_variant,
        'toggle': kybd_toggle,
        'username': new_user,
        'realname': new_realname,
        'password_hash': password_hash,
        'disk_layout': disk_layout,
        'crypto_pass': crypto_pass
    }

    core.print_info("Generating preseed.cfg...")
    preseed_content = generate_preseed(config, user_inputs)
    preseed_path = os.path.join(work_dir, "preseed.cfg")
    with open(preseed_path, 'w') as f:
        f.write(preseed_content)

    if args.dry_run:
        core.dry_run_exit([preseed_path])

    core.print_info("Extracting GRUB and ISOLINUX configurations...")
    mnt_dir = os.path.join(work_dir, "mnt")
    extract_dir = os.path.join(work_dir, "extract")
    os.makedirs(os.path.join(extract_dir, "boot/grub"), exist_ok=True)
    os.makedirs(os.path.join(extract_dir, "isolinux"), exist_ok=True)
    os.makedirs(mnt_dir, exist_ok=True)

    # Robust Mount Failsafe
    core.run_cmd(['sudo', 'mount', '-o', 'loop', iso_path, mnt_dir], capture_output=True)
    try:
        if not os.path.exists(os.path.join(mnt_dir, 'install.amd')):
            core.print_error("This does not look like a Debian Netinst ISO (missing '/install.amd' directory). Did you select an Ubuntu ISO by mistake?")

        shutil.copy(os.path.join(mnt_dir, "boot/grub/grub.cfg"), os.path.join(extract_dir, "boot/grub/grub.cfg"))
        
        isolinux_src = os.path.join(mnt_dir, "isolinux/menu.cfg")
        has_isolinux = os.path.exists(isolinux_src)
        if has_isolinux:
            shutil.copy(isolinux_src, os.path.join(extract_dir, "isolinux/menu.cfg"))
    finally:
        core.run_cmd(['sudo', 'umount', mnt_dir])

    core.print_info("Injecting Autoinstall entry into Debian GRUB (UEFI)...")
    grub_cfg = os.path.join(extract_dir, "boot/grub/grub.cfg")
    os.chmod(grub_cfg, 0o644)
    
    debian_grub_entry = """menuentry "Debian Autoinstall (Wipes Disk)" {
    set gfxpayload=keep
    linux    /install.amd/vmlinuz auto=true priority=critical preseed/file=/cdrom/preseed.cfg --- quiet
    initrd   /install.amd/initrd.gz
}
"""
    with open(grub_cfg, 'r') as f:
        content = f.read()
    content = content.replace("menuentry ", debian_grub_entry + "menuentry ", 1)
    with open(grub_cfg, 'w') as f:
        f.write(content)

    isolinux_cfg = os.path.join(extract_dir, "isolinux/menu.cfg")
    if has_isolinux:
        core.print_info("Injecting Autoinstall entry into ISOLINUX main menu (Legacy BIOS)...")
        os.chmod(isolinux_cfg, 0o644)
        debian_iso_entry = """label autoinstall
    menu label ^Debian Autoinstall (Wipes Disk)
    kernel /install.amd/vmlinuz
    append auto=true priority=critical vga=788 initrd=/install.amd/initrd.gz preseed/file=/cdrom/preseed.cfg --- quiet
"""
        with open(isolinux_cfg, 'r') as f:
            lines = f.readlines()
        with open(isolinux_cfg, 'w') as f:
            for line in lines:
                f.write(line)
                if line.startswith("include stdmenu.cfg"):
                    f.write(debian_iso_entry)

    iso_filename = os.path.basename(iso_path).replace('.iso', '') + '-autoinstall.iso'
    out_iso = os.path.join(work_dir, iso_filename)
    core.print_info(f"Rebuilding ISO: {out_iso}")

    xorriso_cmd = [
        'sudo', 'xorriso',
        '-indev', iso_path,
        '-outdev', out_iso,
        '-boot_image', 'any', 'replay',
        '-map', preseed_path, '/preseed.cfg',
        '-map', grub_cfg, '/boot/grub/grub.cfg'
    ]
    if has_isolinux:
        xorriso_cmd.extend(['-map', isolinux_cfg, '/isolinux/menu.cfg'])

    core.run_cmd(xorriso_cmd, cwd=work_dir)

    core.print_header("Success!")
    core.print_success("Debian Autoinstall ISO created successfully!")
    print(f"Output: {core.Colors.OKGREEN}{out_iso}{core.Colors.ENDC}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        import core
        core.print_error("Process aborted manually by user.")