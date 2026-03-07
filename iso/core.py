#!/usr/bin/env python3

"""
ISO Builder Core Module
Contains shared utilities for parsing YAML without external dependencies,
handling terminal UI, and executing system commands for ISO manipulation.
"""

import os
import sys
import subprocess
import shutil
import getpass
import re

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}========================================================{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}   {text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}========================================================{Colors.ENDC}")

def print_step(text):
    print(f"\n{Colors.OKBLUE}{Colors.BOLD}==> {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKBLUE}[INFO]{Colors.ENDC} {text}")

def print_success(text):
    print(f"{Colors.OKGREEN}[SUCCESS]{Colors.ENDC} {text}")

def print_warning(text):
    print(f"{Colors.WARNING}[WARN]{Colors.ENDC} {text}")

def print_error(text):
    print(f"{Colors.FAIL}[ERROR]{Colors.ENDC} {text}")
    sys.exit(1)

def run_cmd(cmd, check=True, cwd=None, shell=False, capture_output=False):
    """Executes a shell command safely."""
    try:
        return subprocess.run(cmd, check=check, cwd=cwd, shell=shell, text=True, capture_output=capture_output)
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd) if isinstance(cmd, list) else cmd}\nError: {e.stderr if capture_output else e}")

def ask_input(prompt_text, default_val=""):
    """Prompts the user for input with a default value."""
    prompt = f"{Colors.WARNING}? {prompt_text} [{default_val}]: {Colors.ENDC}"
    val = input(prompt).strip()
    return val if val else default_val

def ask_yes_no(prompt_text, default="y"):
    """Prompts the user for a yes/no answer."""
    hint = "[Y/n]" if default.lower() == 'y' else "[y/N]"
    prompt = f"{Colors.WARNING}? {prompt_text} {hint}: {Colors.ENDC}"
    val = input(prompt).strip().lower()
    if not val:
        val = default.lower()
    return val in ['y', 'yes']

def ask_password(prompt_text):
    """Prompts for a password securely without echoing."""
    print(f"{Colors.WARNING}? {prompt_text}: {Colors.ENDC}", end="", flush=True)
    return getpass.getpass("")

def hash_password(plain_password):
    """Hashes a password using openssl -6 (SHA512)."""
    if not plain_password:
        return None
    result = run_cmd(['openssl', 'passwd', '-6', plain_password], capture_output=True)
    return result.stdout.strip()

def setup_work_dir(default_dir):
    """Prompts for and prepares the working directory."""
    work_dir = ask_input("Enter working directory", default_dir)
    work_dir = os.path.expanduser(work_dir)

    if os.path.exists(work_dir):
        print_warning(f"Directory {work_dir} already exists.")
        if ask_yes_no("Clean up and recreate?"):
            print_info("Cleaning up old workspace...")
            run_cmd(['sudo', 'rm', '-rf', work_dir])
    
    os.makedirs(work_dir, exist_ok=True)
    return work_dir

def check_dependencies(deps):
    """Ensure required system tools are installed."""
    missing = [dep for dep in deps if not shutil.which(dep)]
    if missing:
        print_error(f"Missing required tools: {', '.join(missing)}\nPlease install them: sudo apt install {' '.join(missing)}")

def get_yaml_value(filepath, key):
    """Rudimentary parser to extract a simple key-value from the YAML file."""
    if not os.path.exists(filepath):
        return ""
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip().startswith(f"{key}:"):
                val = line.split(':', 1)[1].strip()
                return val.strip("\"'")
    return ""

def parse_simple_yaml(filepath):
    """
    A lightweight, custom YAML parser that requires NO external dependencies.
    Fully updated to process and sandbox both 'autoinstall' and 'x-os-overrides'.
    """
    if not os.path.exists(filepath):
        print_error(f"YAML file not found: {filepath}")

    data = {
        'locale': 'en_US.UTF-8', 'keyboard': 'us', 'hostname': 'ubuntu-mini',
        'username': 'user', 'realname': 'User', 'password': '',
        'packages': [], 'snaps': [], 'late_cmds': []
    }
    
    overrides = {
        'ubuntu': {'packages': [], 'late_cmds': []},
        'debian': {'packages': [], 'late_cmds': []}
    }
    
    current_block = None
    current_os = None
    current_snap = {}
    
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'): continue
            
            # Detect root blocks
            if not line.startswith(' ') and line.endswith(':\n'):
                if line.startswith('autoinstall:'):
                    current_block = 'autoinstall'
                elif line.startswith('x-os-overrides:'):
                    current_block = 'overrides'
                else:
                    current_block = None
                continue
                
            # Process x-os-overrides section
            if current_block == 'overrides':
                if line.startswith('  ubuntu:'): current_os = 'ubuntu'
                elif line.startswith('  debian:'): current_os = 'debian'
                elif line.startswith('    packages:'): current_block = f'overrides_{current_os}_packages'
                elif line.startswith('    late-commands:'): current_block = f'overrides_{current_os}_cmds'
                    
            elif current_block and current_block.startswith('overrides_'):
                if line.startswith('  ubuntu:'): 
                    current_os = 'ubuntu'
                    current_block = 'overrides'
                elif line.startswith('  debian:'): 
                    current_os = 'debian'
                    current_block = 'overrides'
                elif line.startswith('    packages:'):
                    current_block = f'overrides_{current_os}_packages'
                elif line.startswith('    late-commands:'):
                    current_block = f'overrides_{current_os}_cmds'
                elif stripped.startswith('- '):
                    if current_block.endswith('_packages'):
                        overrides[current_os]['packages'].append(stripped[2:].strip(' "\''))
                    elif current_block.endswith('_cmds'):
                        overrides[current_os]['late_cmds'].append(stripped[2:].strip())

            # Process main autoinstall section
            elif current_block == 'autoinstall' or (current_block and current_block in ['packages', 'snaps', 'late-commands']):
                if line.startswith('  locale:'): data['locale'] = stripped.split(':', 1)[1].strip(' "\'')
                elif line.startswith('    layout:'): data['keyboard'] = stripped.split(':', 1)[1].strip(' "\'')
                elif line.startswith('    hostname:'): data['hostname'] = stripped.split(':', 1)[1].strip(' "\'')
                elif line.startswith('    username:'): data['username'] = stripped.split(':', 1)[1].strip(' "\'')
                elif line.startswith('    realname:'): data['realname'] = stripped.split(':', 1)[1].strip(' "\'')
                elif line.startswith('    password:'): data['password'] = stripped.split(':', 1)[1].strip(' "\'')
                
                elif line.startswith('  packages:'): current_block = 'packages'
                elif line.startswith('  snaps:'): current_block = 'snaps'
                elif line.startswith('  late-commands:'): current_block = 'late-commands'
                
                elif current_block == 'packages' and stripped.startswith('- '):
                    data['packages'].append(stripped[2:].strip(' "\''))
                elif current_block == 'late-commands' and stripped.startswith('- '):
                    data['late_cmds'].append(stripped[2:].strip())
                elif current_block == 'snaps':
                    if stripped.startswith('- name:'):
                        if current_snap: data['snaps'].append(current_snap)
                        current_snap = {'name': stripped.split(':', 1)[1].strip(' "\''), 'classic': False}
                    elif stripped.startswith('classic:'):
                        val = stripped.split(':', 1)[1].strip(' "\'').lower()
                        current_snap['classic'] = (val == 'true' or val == 'yes')
                        
    if current_snap:
         data['snaps'].append(current_snap)
         
    return {"autoinstall": data, "x-os-overrides": overrides}

def merge_os_overrides(config, os_name):
    """Merges 'x-os-overrides' into the main autoinstall config for data-driven outputs (like Debian)."""
    data = config.get('autoinstall', {})
    ovr = config.get('x-os-overrides', {}).get(os_name, {})
    
    if 'packages' in ovr:
        data['packages'].extend(ovr['packages'])
    if 'late_cmds' in ovr:
        data['late_cmds'].extend(ovr['late_cmds'])
        
    config['autoinstall'] = data
    return config

def inject_yaml_list(filepath, section, items):
    """Physically injects list items into a specific section of a YAML file.
    Appends them to the END of the list to preserve the execution order.
    """
    if not items:
        return
        
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    in_autoinstall = False
    in_section = False
    insert_idx = -1
    
    for i, line in enumerate(lines):
        if line.startswith('autoinstall:'):
            in_autoinstall = True
        elif in_autoinstall and line.startswith(f'  {section}:'):
            in_section = True
            insert_idx = i + 1
        elif in_section:
            # Keep advancing index until we hit the end of the list block
            if line.startswith('    -') or line.strip() == '' or line.strip().startswith('#'):
                insert_idx = i + 1
            elif line.strip() != '' and not line.startswith('    '):
                break
                
    if insert_idx != -1:
        # Insert in reverse so they appear in correct forward order at the BOTTOM of the list
        for item in reversed(items):
            lines.insert(insert_idx, f"    - {item}\n")
            
        with open(filepath, 'w') as f:
            f.writelines(lines)
    else:
        print_warning(f"Could not find '{section}:' block in {filepath} to inject OS overrides.")

def replace_in_file(filepath, pattern, replacement):
    """Regex based replacement in a text file (safe sed equivalent)."""
    with open(filepath, 'r') as f:
        content = f.read()
    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    with open(filepath, 'w') as f:
        f.write(content)