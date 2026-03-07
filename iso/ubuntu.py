#!/usr/bin/env python3

"""
Ubuntu Automated ISO Builder
Translates the full interactive flow of ubuntu.sh into a clean Python script.
"""

import os
import shutil
import core
import argparse

DEPENDENCIES = ['xorriso', 'rsync', 'openssl']
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

def main():
    parser = argparse.ArgumentParser(description="Ubuntu Autoinstall ISO Builder")
    parser.add_argument('--dry-run', action='store_true', help="Generate configs only, skip ISO build")
    args = parser.parse_args()

    core.print_header("Step 1: Environment & Workspace Setup")
    if not args.dry_run:
        core.check_dependencies(DEPENDENCIES)

    work_dir = core.setup_work_dir("~/ubuntu-autoinstall")
    os.makedirs(os.path.join(work_dir, 'extract/nocloud'), exist_ok=True)

    if not args.dry_run:
        core.print_header("Step 2: ISO Preparation")
        default_iso = "/mnt/keep/os/linux/Ubuntu/ubuntu-25.10-desktop-amd64.iso"
        iso_path = core.ask_input("Enter path to source Ubuntu ISO", default_iso)
        iso_path = os.path.expanduser(iso_path)

        if not os.path.exists(iso_path):
            core.print_error(f"ISO file not found at {iso_path}")

        core.print_info("Mounting ISO to extract bootloader config...")
        mnt_dir = os.path.join(work_dir, 'mnt')
        extract_dir = os.path.join(work_dir, 'extract')
        os.makedirs(mnt_dir, exist_ok=True)
        os.makedirs(os.path.join(extract_dir, 'boot/grub'), exist_ok=True)
        
        core.run_cmd(['sudo', 'mount', '-o', 'loop', iso_path, mnt_dir])
        shutil.copy(os.path.join(mnt_dir, 'boot/grub/grub.cfg'), os.path.join(extract_dir, 'boot/grub/grub.cfg'))
        core.run_cmd(['sudo', 'umount', mnt_dir])
    else:
        extract_dir = os.path.join(work_dir, 'extract')
        core.print_info("Dry-Run enabled. Skipping ISO mount/extraction.")

    core.print_header("Step 3: Configuration & Customization")
    default_yaml = os.path.join(SCRIPT_DIR, "autoinstall.yaml")
    yaml_path = core.ask_input("Enter path to autoinstall.yaml template", default_yaml)
    yaml_path = os.path.expanduser(yaml_path)

    if not os.path.exists(yaml_path):
        core.print_error(f"Template file not found at {yaml_path}")

    core.print_info("Extracting default values from template...")
    config = core.parse_simple_yaml(yaml_path)
    data = config.get('autoinstall', {})

    new_hostname = core.ask_input("Enter Hostname", data.get('hostname', 'ubuntu-mini'))
    new_locale = core.ask_input("Enter System Locale (Hint: en_US.UTF-8)", data.get('locale', 'en_US.UTF-8'))
    new_timezone = core.ask_input("Enter Timezone (e.g., Europe/Oslo)", data.get('timezone', 'UTC'))
    
    yaml_layout = core.get_yaml_value(yaml_path, "layout") or "us"
    kybd_layout = core.ask_input("Enter Keyboard Layout", yaml_layout)
    kybd_variant = core.ask_input("Enter Keyboard Variant", "")
    
    new_user = core.ask_input("Enter Username", data.get('username', 'ubuntu'))
    new_realname = core.ask_input("Enter Real Name", data.get('realname', 'User'))
    
    plain_password = core.ask_password("Enter New Password (blank to keep template hash)")
    password_hash = core.hash_password(plain_password) if plain_password else None

    # Disk Partitioning Prompt
    print()
    disk_layout = core.ask_choice("Select Disk Partitioning", ["Standard (Direct Wipe)", "LVM (Logical Volume Manager)"], default=1)

    # Run the dynamic YAML prompts!
    config = core.run_os_prompts(config, 'ubuntu')

    core.print_header("Step 4: Generating Autoinstall Files")
    core.print_info("Processing user-data...")
    
    user_data_path = os.path.join(extract_dir, 'nocloud/user-data')
    shutil.copy(yaml_path, user_data_path)

    ubuntu_ovr = config.get('x-os-overrides', {}).get('ubuntu', {})
    core.inject_yaml_list(user_data_path, 'packages', ubuntu_ovr.get('packages', []))
    core.inject_yaml_list(user_data_path, 'late-commands', ubuntu_ovr.get('late_cmds', []))
    core.inject_yaml_snaps(user_data_path, ubuntu_ovr.get('snaps', []))
    
    with open(user_data_path, 'r') as f:
        content = f.read()
    clean_content = content.split('x-os-overrides:')[0].rstrip() + '\n'
    with open(user_data_path, 'w') as f:
        f.write(clean_content)

    core.replace_in_file(user_data_path, r"^(\s*hostname:).*", rf"\1 {new_hostname}")
    core.replace_in_file(user_data_path, r"^(\s*locale:).*", rf"\1 {new_locale}")
    core.replace_in_file(user_data_path, r"^(\s*timezone:).*", rf"\1 {new_timezone}")
    core.replace_in_file(user_data_path, r"^(\s*username:).*", rf"\1 {new_user}")
    core.replace_in_file(user_data_path, r"^(\s*realname:).*", rf'\1 "{new_realname}"')
    core.replace_in_file(user_data_path, r"^(\s*layout:)\s*\".*\"", rf'\1 "{kybd_layout}"')
    core.replace_in_file(user_data_path, r"^(\s*variant:)\s*\".*\"", rf'\1 "{kybd_variant}"')
    
    # Safely swap Storage to LVM if selected
    if disk_layout == 1:
        core.replace_in_file(user_data_path, r"^(\s*name:)\s*direct", rf"\1 lvm")

    if password_hash:
        core.replace_in_file(user_data_path, r"^(\s*password:).*", rf'\1 "{password_hash}"')

    yaml_user = data.get('username', 'ubuntu')
    core.replace_in_file(user_data_path, rf"(\s){yaml_user}(\s|$)", rf"\1{new_user}\2")
    core.replace_in_file(user_data_path, rf"(\s){yaml_user}(\s|$)", rf"\1{new_user}\2")

    core.print_info("Generating meta-data...")
    meta_data_path = os.path.join(extract_dir, 'nocloud/meta-data')
    with open(meta_data_path, 'w') as f:
        f.write(f"instance-id: {new_hostname}-autoinstall\n")
        f.write(f"local-hostname: {new_hostname}\n")

    if args.dry_run:
        # core.print_header("Dry Run Complete!")
        # core.print_success(f"Generated configs safely dropped in {extract_dir}/nocloud/")
        # sys.exit(0)
        core.dry_run_exit([user_data_path, meta_data_path])

    core.print_header("Step 5: Modifying Bootloader & Building ISO")
    grub_cfg = os.path.join(extract_dir, 'boot/grub/grub.cfg')
    if os.path.exists(grub_cfg):
        core.run_cmd(['chmod', 'u+w', grub_cfg])
        autoinstall_entry = """menuentry "Ubuntu Autoinstall (Wipes Disk)" {
        set gfxpayload=keep
        linux   /casper/vmlinuz  quiet splash autoinstall ds=nocloud\\;s=/cdrom/nocloud/ ---
        initrd  /casper/initrd
}
"""
        with open(grub_cfg, 'r') as f:
            content = f.read()
        content = content.replace("menuentry ", autoinstall_entry + "menuentry ", 1)
        with open(grub_cfg, 'w') as f:
            f.write(content)
        core.print_success("GRUB entry added successfully.")

    iso_filename = os.path.basename(iso_path).replace('.iso', '') + '-autoinstall.iso'
    out_iso = os.path.join(work_dir, iso_filename)
    
    core.print_info(f"Running xorriso to build final ISO: {out_iso}...")
    xorriso_cmd = [
        'sudo', 'xorriso',
        '-indev', iso_path,
        '-outdev', out_iso,
        '-boot_image', 'any', 'replay',
        '-map', os.path.join(work_dir, 'extract/nocloud'), '/nocloud',
        '-map', grub_cfg, '/boot/grub/grub.cfg'
    ]
    core.run_cmd(xorriso_cmd, cwd=work_dir)

    user = os.environ.get('SUDO_USER', os.environ.get('USER'))
    if user:
        core.run_cmd(['sudo', 'chown', '-R', f"{user}:{user}", work_dir])

    core.print_header("Success!")
    print(f"1. Custom ISO:   {core.Colors.OKGREEN}{out_iso}{core.Colors.ENDC}")
    print(f"2. Workspace:    {core.Colors.OKGREEN}{work_dir}{core.Colors.ENDC}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        import core
        core.print_error("Process aborted manually by user.")