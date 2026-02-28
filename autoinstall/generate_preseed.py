#!/usr/bin/env python3
import sys
import os
import argparse

def get_simple_yaml_data(filepath):
    # A basic parser that avoids the need for the external pyyaml library
    data = {
        'locale': 'en_US.UTF-8',
        'keyboard': 'us',
        'hostname': 'debian-mini',
        'username': 'user',
        'realname': 'User',
        'password': '',
        'packages': [],
        'snaps': [],
        'late_cmds': []
    }
    
    if not os.path.exists(filepath):
        print(f"Warning: {filepath} not found. Using default values.")
        return data

    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    current_block = None
    current_snap = {}
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
            
        # Parse basic identity and config values
        if line.startswith('  locale:'):
            data['locale'] = stripped.split(':', 1)[1].strip(' "\'')
        elif line.startswith('    layout:'):
            data['keyboard'] = stripped.split(':', 1)[1].strip(' "\'')
        elif line.startswith('    hostname:'):
            data['hostname'] = stripped.split(':', 1)[1].strip(' "\'')
        elif line.startswith('    username:'):
            data['username'] = stripped.split(':', 1)[1].strip(' "\'')
        elif line.startswith('    realname:'):
            data['realname'] = stripped.split(':', 1)[1].strip(' "\'')
        elif line.startswith('    password:'):
            data['password'] = stripped.split(':', 1)[1].strip(' "\'')
            
        # Track list blocks
        elif line.startswith('  packages:'):
            current_block = 'packages'
        elif line.startswith('  snaps:'):
            current_block = 'snaps'
        elif line.startswith('  late-commands:'):
            current_block = 'late-commands'
        elif line.startswith('  ') and not line.startswith('    ') and not stripped.startswith('-'):
            current_block = None  # Reset block if we hit another top-level key
            
        # Extract list items based on the active block
        elif current_block == 'packages' and stripped.startswith('- '):
            data['packages'].append(stripped[2:].strip(' "\''))
        elif current_block == 'late-commands' and stripped.startswith('- '):
            data['late_cmds'].append(stripped[2:].strip())
        elif current_block == 'snaps':
            if stripped.startswith('- name:'):
                if current_snap:
                    data['snaps'].append(current_snap)
                current_snap = {'name': stripped.split(':', 1)[1].strip(' "\''), 'classic': False}
            elif stripped.startswith('classic:'):
                val = stripped.split(':', 1)[1].strip(' "\'').lower()
                current_snap['classic'] = (val == 'true' or val == 'yes')
                
    if current_snap:
         data['snaps'].append(current_snap)
         
    return data

def main():
    # Setup built-in arguments parser for dynamic overrides
    parser = argparse.ArgumentParser(description="Generate Debian preseed from Ubuntu autoinstall YAML")
    parser.add_argument("--yaml", default="autoinstall/ubuntu.yaml", help="Source YAML file")
    parser.add_argument("--out", default="autoinstall/preseed.cfg", help="Output preseed file")
    parser.add_argument("--hostname", help="Override hostname")
    parser.add_argument("--username", help="Override username")
    parser.add_argument("--realname", help="Override real name")
    # Password CLI argument removed for security!
    
    args = parser.parse_args()

    # Parse the YAML file
    data = get_simple_yaml_data(args.yaml)
    
    # Apply CLI overrides if they were provided
    hostname = args.hostname if args.hostname else data['hostname']
    username = args.username if args.username else data['username']
    realname = args.realname if args.realname else data['realname']
    
    # Securely fetch password from environment variable (set by bash script), fallback to YAML
    password = os.environ.get('PRESEED_PASSWORD_HASH', data['password'])
    locale = data['locale']
    keyboard = data['keyboard']
    
    packages = data['packages']
    if data['snaps'] and 'snapd' not in packages:
        packages.append('snapd')
        
    packages_str = " ".join(packages)
    snaps = data['snaps']
    late_cmds = data['late_cmds']

    # Build the preseed content
    preseed = f"""# ==========================================
# AUTO-GENERATED DEBIAN PRESEED
# Generated from {args.yaml}
# ==========================================

# --- Localization & Keyboard ---
d-i debian-installer/locale string {locale}
d-i keyboard-configuration/xkb-keymap select {keyboard}

# --- Network & Mirror ---
d-i netcfg/get_hostname string {hostname}
d-i netcfg/get_domain string unassigned-domain
d-i mirror/country string manual
d-i mirror/http/hostname string deb.debian.org
d-i mirror/http/directory string /debian
d-i mirror/http/proxy string

# --- User Creation ---
d-i passwd/root-login boolean false
d-i passwd/user-fullname string {realname}
d-i passwd/username string {username}
d-i passwd/user-password-crypted password {password}

# --- Clock & Timezone ---
d-i clock-setup/utc boolean true
d-i time/zone string UTC

# --- Storage / Partitioning (Equivalent to direct layout) ---
d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true

# --- Base System & Packages ---
# Install standard utilities and a basic GNOME desktop environment
tasksel tasksel/first multiselect standard, desktop, gnome-desktop
d-i pkgsel/include string {packages_str}
d-i pkgsel/upgrade select full-upgrade
popularity-contest popularity-contest/participate boolean false

# --- Bootloader ---
d-i grub-installer/only_debian boolean true
d-i grub-installer/with_other_os boolean true
d-i grub-installer/bootdev  string default

# --- Late Commands (Post-Install Scripts) ---
"""

    # Process post-install scripts
    preseed += "d-i preseed/late_command string \\\n"
    preseed += "  echo '#!/bin/bash' > /target/root/post_install.sh; \\\n"
    
    # 1. Translate Snaps
    if snaps:
        preseed += "  echo 'systemctl start snapd' >> /target/root/post_install.sh; \\\n"
        for snap in snaps:
            name = snap.get('name')
            classic = "--classic" if snap.get('classic') else ""
            preseed += f"  echo 'snap install {name} {classic}' >> /target/root/post_install.sh; \\\n"

    # 2. Translate Late Commands
    for cmd in late_cmds:
        if 'ubuntu-drivers' in cmd:
            preseed += f"  echo '# Skipped ubuntu-drivers (Ubuntu specific)' >> /target/root/post_install.sh; \\\n"
            continue
            
        clean_cmd = cmd.replace('curtin in-target -- ', '')
        clean_cmd = clean_cmd.replace("'", "'\\''") 
        preseed += f"  echo '{clean_cmd}' >> /target/root/post_install.sh; \\\n"

    preseed += "  in-target chmod +x /root/post_install.sh; \\\n"
    preseed += "  in-target /bin/bash /root/post_install.sh; \\\n"
    preseed += "  in-target rm /root/post_install.sh\n"
    
    # --- Finish ---
    preseed += "\n# Reboot when done\nd-i finish-install/reboot_in_progress note\n"

    with open(args.out, 'w') as f:
        f.write(preseed)
    
    print(f"Successfully generated {args.out} from {args.yaml}")
    print(f"  -> Hostname: {hostname}")
    print(f"  -> Username: {username}")

if __name__ == "__main__":
    main()