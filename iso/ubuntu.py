#!/usr/bin/env python3

"""
Ubuntu Automated ISO Builder
Translates the full interactive flow of ubuntu.sh into a clean Python script.
"""

import os
import sys
import shutil
import core

DEPENDENCIES = ['xorriso', 'rsync', 'openssl']
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

def main():
    core.print_header("Step 1: Environment & Workspace Setup")
    core.check_dependencies(DEPENDENCIES)

    # 1. Workspace
    work_dir = core.setup_work_dir("~/ubuntu-autoinstall")
    
    os.makedirs(os.path.join(work_dir, 'mnt'), exist_ok=True)
    os.makedirs(os.path.join(work_dir, 'extract/nocloud'), exist_ok=True)

    # 2. ISO Path
    core.print_header("Step 2: ISO Preparation")
    default_iso = "/mnt/keep/os/linux/Ubuntu/ubuntu-25.10-desktop-amd64.iso"
    iso_path = core.ask_input("Enter path to source Ubuntu ISO", default_iso)
    iso_path = os.path.expanduser(iso_path)

    if not os.path.exists(iso_path):
        core.print_error(f"ISO file not found at {iso_path}")

    # Mount and extract
    core.print_info("Mounting ISO to extract bootloader config...")
    mnt_dir = os.path.join(work_dir, 'mnt')
    extract_dir = os.path.join(work_dir, 'extract')
    
    os.makedirs(os.path.join(extract_dir, 'boot/grub'), exist_ok=True)
    
    core.run_cmd(['sudo', 'mount', '-o', 'loop', iso_path, mnt_dir])
    shutil.copy(os.path.join(mnt_dir, 'boot/grub/grub.cfg'), os.path.join(extract_dir, 'boot/grub/grub.cfg'))
    core.run_cmd(['sudo', 'umount', mnt_dir])

    # 3. YAML Config & Details
    core.print_header("Step 3: Configuration & Customization")
    default_yaml = os.path.join(SCRIPT_DIR, "autoinstall.yaml")
    yaml_path = core.ask_input("Enter path to autoinstall.yaml template", default_yaml)
    yaml_path = os.path.expanduser(yaml_path)

    if not os.path.exists(yaml_path):
        core.print_error(f"Template file not found at {yaml_path}")

    core.print_info("Extracting default values from template...")
    yaml_hostname = core.get_yaml_value(yaml_path, "hostname") or "ubuntu-mini"
    yaml_locale = core.get_yaml_value(yaml_path, "locale") or "en_US.UTF-8"
    yaml_layout = core.get_yaml_value(yaml_path, "layout") or "us"
    yaml_variant = core.get_yaml_value(yaml_path, "variant") or ""
    yaml_user = core.get_yaml_value(yaml_path, "username") or "ubuntu"
    yaml_realname = core.get_yaml_value(yaml_path, "realname") or "User"

    new_hostname = core.ask_input("Enter Hostname", yaml_hostname)
    print(f"{core.Colors.OKBLUE}Hint:{core.Colors.ENDC} en_US.UTF-8, nb_NO.UTF-8")
    new_locale = core.ask_input("Enter System Locale", yaml_locale)
    print(f"{core.Colors.OKBLUE}Hint:{core.Colors.ENDC} 'no' (Norwegian), 'us' (English US)")
    kybd_layout = core.ask_input("Enter Keyboard Layout", yaml_layout)
    kybd_variant = core.ask_input("Enter Keyboard Variant", yaml_variant)
    new_user = core.ask_input("Enter Username", yaml_user)
    new_realname = core.ask_input("Enter Real Name", yaml_realname)
    
    plain_password = core.ask_password("Enter New Password (blank to keep template hash)")
    password_hash = core.hash_password(plain_password) if plain_password else None

    # 4. Generate Autoinstall Files
    core.print_header("Step 4: Generating Autoinstall Files")
    core.print_info("Processing user-data...")
    
    user_data_path = os.path.join(extract_dir, 'nocloud/user-data')
    shutil.copy(yaml_path, user_data_path)

    # --- INJECT UBUNTU OVERRIDES ---
    config = core.parse_simple_yaml(yaml_path)
    ubuntu_ovr = config.get('x-os-overrides', {}).get('ubuntu', {})
    
    core.inject_yaml_list(user_data_path, 'packages', ubuntu_ovr.get('packages', []))
    core.inject_yaml_list(user_data_path, 'late-commands', ubuntu_ovr.get('late_cmds', []))
    
    # --- REMOVE x-os-overrides BLOCK ---
    with open(user_data_path, 'r') as f:
        content = f.read()
        
    # Safely truncate everything from x-os-overrides onwards, leaving a clean EOF newline
    clean_content = content.split('x-os-overrides:')[0].rstrip() + '\n'
    
    with open(user_data_path, 'w') as f:
        f.write(clean_content)
    # -------------------------------

    # Safe text replacements (Strict Regex to prevent YAML corruption)
    core.replace_in_file(user_data_path, r"^(\s*hostname:).*", rf"\1 {new_hostname}")
    core.replace_in_file(user_data_path, r"^(\s*locale:).*", rf"\1 {new_locale}")
    core.replace_in_file(user_data_path, r"^(\s*username:).*", rf"\1 {new_user}")
    core.replace_in_file(user_data_path, r"^(\s*realname:).*", rf'\1 "{new_realname}"')
    
    # FIX: Ensure we only target layout/variant keys that have values on the same line (with quotes),
    # completely avoiding the 'layout:' key inside the 'storage:' block!
    core.replace_in_file(user_data_path, r"^(\s*layout:)\s*\".*\"", rf'\1 "{kybd_layout}"')
    core.replace_in_file(user_data_path, r"^(\s*variant:)\s*\".*\"", rf'\1 "{kybd_variant}"')
    
    if password_hash:
        core.replace_in_file(user_data_path, r"^(\s*password:).*", rf'\1 "{password_hash}"')

    # Smart username replace in shell commands
    core.replace_in_file(user_data_path, rf"(\s){yaml_user}(\s|$)", rf"\1{new_user}\2")
    core.replace_in_file(user_data_path, rf"(\s){yaml_user}(\s|$)", rf"\1{new_user}\2")

    core.print_info("Generating meta-data...")
    meta_data_path = os.path.join(extract_dir, 'nocloud/meta-data')
    with open(meta_data_path, 'w') as f:
        f.write(f"instance-id: {new_hostname}-autoinstall\n")
        f.write(f"local-hostname: {new_hostname}\n")

    # 5. Bootloader and Rebuild
    core.print_header("Step 5: Modifying Bootloader & Building ISO")
    grub_cfg = os.path.join(extract_dir, 'boot/grub/grub.cfg')
    
    if os.path.exists(grub_cfg):
        core.print_info("Injecting Autoinstall entry into GRUB...")
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
    else:
        core.print_warning("grub.cfg not found. Skipping bootloader modification.")

    # 6. Repack ISO
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

    # Chown back to user
    user = os.environ.get('SUDO_USER', os.environ.get('USER'))
    if user:
        core.run_cmd(['sudo', 'chown', '-R', f"{user}:{user}", work_dir])

    core.print_header("Success!")
    print(f"1. Custom ISO:   {core.Colors.OKGREEN}{out_iso}{core.Colors.ENDC}")
    print(f"2. Workspace:    {core.Colors.OKGREEN}{work_dir}{core.Colors.ENDC}")
    core.print_info("Process complete. You can now flash the ISO to a USB drive.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        core.print_error("Process aborted manually by user.")