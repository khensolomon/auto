#!/usr/bin/env python3

"""
ISO Builder Core Module
Contains shared utilities for parsing YAML, dynamic prompts, and building.
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
    try:
        return subprocess.run(cmd, check=check, cwd=cwd, shell=shell, text=True, capture_output=capture_output)
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd) if isinstance(cmd, list) else cmd}\nError: {e.stderr if capture_output else e}")

def dry_run_exit(filepaths):
    """Prints the contents of the generated config files and exits safely."""
    print_header("Dry Run Complete!")
    for fp in filepaths:
        if os.path.exists(fp):
            print(f"\n{Colors.WARNING}>>> START OF {os.path.basename(fp)} <<<{Colors.ENDC}")
            with open(fp, 'r') as f:
                print(f.read().strip())
            print(f"{Colors.WARNING}>>> END OF {os.path.basename(fp)} <<<{Colors.ENDC}")
    
    print(f"\n{Colors.OKGREEN}[SUCCESS]{Colors.ENDC} Generated configs safely dropped in the workspace.")
    sys.exit(1)

def ask_input(prompt_text, default_val=""):
    prompt = f"{Colors.WARNING}{prompt_text} [{default_val}]: {Colors.ENDC}"
    val = input(prompt).strip()
    return val if val else default_val

def ask_yes_no(prompt_text, default="y"):
    hint = "[Y/n]" if default.lower() in ['y', 'yes'] else "[y/N]"
    prompt = f"{Colors.WARNING}{prompt_text} {hint}: {Colors.ENDC}"
    val = input(prompt).strip().lower()
    if not val:
        val = 'y' if default.lower() in ['y', 'yes'] else 'n'
    return val in ['y', 'yes']

def ask_choice(question, choices, default=None):
    print(f"{Colors.WARNING}{question}{Colors.ENDC}")
    for i, choice in enumerate(choices, 1):
        if default and str(default) == str(i):
            print(f"  {i}. {choice} (default)")
        else:
            print(f"  {i}. {choice}")
    
    default_hint = f" [{default}]" if default else ""
    while True:
        val = input(f"{Colors.WARNING}Select an option [1-{len(choices)}]{default_hint}: {Colors.ENDC}").strip()
        if not val and default:
            return int(default) - 1
        try:
            idx = int(val)
            if 1 <= idx <= len(choices):
                return idx - 1
        except ValueError:
            pass
        print(f"  Please enter a valid number between 1 and {len(choices)}.")

def ask_password(prompt_text):
    print(f"{Colors.WARNING}{prompt_text}: {Colors.ENDC}", end="", flush=True)
    return getpass.getpass("")

def hash_password(plain_password):
    if not plain_password:
        return None
    result = run_cmd(['openssl', 'passwd', '-6', plain_password], capture_output=True)
    return result.stdout.strip()

def setup_work_dir(default_dir):
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
    missing = [dep for dep in deps if not shutil.which(dep)]
    if missing:
        print_error(f"Missing required tools: {', '.join(missing)}\nPlease install them: sudo apt install {' '.join(missing)}")

def get_yaml_value(filepath, key):
    if not os.path.exists(filepath):
        return ""
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip().startswith(f"{key}:"):
                val = line.split(':', 1)[1].strip()
                if val.startswith('"') and val.endswith('"'): return val[1:-1]
                if val.startswith("'") and val.endswith("'"): return val[1:-1]
                return val
    return ""

def _clean_val(val):
    v = val.strip()
    if v.startswith('"') and v.endswith('"'): return v[1:-1]
    if v.startswith("'") and v.endswith("'"): return v[1:-1]
    return v

def parse_simple_yaml(filepath):
    if not os.path.exists(filepath):
        print_error(f"YAML file not found: {filepath}")

    data = {
        'locale': 'en_US.UTF-8', 'timezone': 'UTC', 'keyboard': 'us', 'hostname': 'ubuntu-mini',
        'username': 'user', 'realname': 'User', 'password': '',
        'packages': [], 'snaps': [], 'late_cmds': []
    }
    
    overrides = {
        'shared': {'packages': [], 'late_cmds': [], 'prompts': []},
        'ubuntu': {'packages': [], 'late_cmds': [], 'prompts': []},
        'debian': {'packages': [], 'late_cmds': [], 'prompts': []}
    }
    
    current_block = None
    current_os = None
    current_snap = {}
    current_prompt = None
    current_choice = None
    current_list_target = None
    current_list_key = None
    
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'): continue
            
            if not line.startswith(' ') and line.endswith(':\n'):
                if line.startswith('autoinstall:'): current_block = 'autoinstall'
                elif line.startswith('x-os-overrides:'): current_block = 'overrides'
                else: current_block = None
                continue
                
            if current_block and current_block.startswith('overrides'):
                if line.startswith('  shared:'):
                    current_os = 'shared'
                    current_block = 'overrides'
                elif line.startswith('  ubuntu:'):
                    current_os = 'ubuntu'
                    current_block = 'overrides'
                elif line.startswith('  debian:'):
                    current_os = 'debian'
                    current_block = 'overrides'
                elif line.startswith('    packages:'):
                    current_block = f'overrides_{current_os}_packages'
                elif line.startswith('    late-commands:'):
                    current_block = f'overrides_{current_os}_cmds'
                elif line.startswith('    prompts:'):
                    current_block = f'overrides_{current_os}_prompts'
                    
                elif current_block.endswith('_packages') and stripped.startswith('- '):
                    overrides[current_os]['packages'].append(_clean_val(stripped[2:]))
                elif current_block.endswith('_cmds') and stripped.startswith('- '):
                    overrides[current_os]['late_cmds'].append(_clean_val(stripped[2:]))
                    
                elif current_block.endswith('_prompts'):
                    if line.startswith('      - ask:'):
                        current_prompt = {'ask': _clean_val(line.split(':', 1)[1]), 'choices': [], 'ubuntu': {}, 'debian': {}}
                        overrides[current_os]['prompts'].append(current_prompt)
                        current_list_target = current_prompt
                        current_list_key = None
                    elif line.startswith('        default:'):
                        current_prompt['default'] = _clean_val(line.split(':', 1)[1])
                    elif line.startswith('        ubuntu:'):
                        current_list_target = current_prompt['ubuntu']
                    elif line.startswith('        debian:'):
                        current_list_target = current_prompt['debian']
                    elif line.startswith('        packages:') or line.startswith('          packages:'):
                        current_list_key = 'packages'
                        current_list_target[current_list_key] = []
                        val = line.split(':', 1)[1].strip()
                        if val.startswith('[') and val.endswith(']'):
                            val = val[1:-1]
                            if val: current_list_target[current_list_key] = [_clean_val(p) for p in val.split(',')]
                    elif line.startswith('        late-commands:') or line.startswith('          late-commands:'):
                        current_list_key = 'late_cmds'
                        current_list_target[current_list_key] = []
                        val = line.split(':', 1)[1].strip()
                        if val.startswith('[') and val.endswith(']'):
                            val = val[1:-1]
                            if val: current_list_target[current_list_key] = [_clean_val(p) for p in val.split(',')]
                    elif line.startswith('        snaps:') or line.startswith('          snaps:'):
                        current_list_key = 'snaps'
                        current_list_target[current_list_key] = []
                        val = line.split(':', 1)[1].strip()
                        if val.startswith('[') and val.endswith(']'):
                            val = val[1:-1]
                            if val: current_list_target[current_list_key] = [_clean_val(p) for p in val.split(',')]
                    elif line.startswith('        choices:'):
                        pass
                    elif line.startswith('          - label:'):
                        current_choice = {'label': _clean_val(line.split(':', 1)[1]), 'ubuntu': {}, 'debian': {}}
                        current_prompt['choices'].append(current_choice)
                        current_list_target = current_choice
                        current_list_key = None
                    elif stripped.startswith('- ') and current_list_key:
                        current_list_target[current_list_key].append(_clean_val(stripped[2:]))

            elif current_block == 'autoinstall' or (current_block and current_block in ['packages', 'snaps', 'late-commands']):
                if line.startswith('  locale:'): data['locale'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('  timezone:'): data['timezone'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('    layout:'): data['keyboard'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('    hostname:'): data['hostname'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('    username:'): data['username'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('    realname:'): data['realname'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('    password:'): data['password'] = _clean_val(line.split(':', 1)[1])
                elif line.startswith('  packages:'): current_block = 'packages'
                elif line.startswith('  snaps:'): current_block = 'snaps'
                elif line.startswith('  late-commands:'): current_block = 'late-commands'
                
                elif current_block == 'packages' and stripped.startswith('- '):
                    data['packages'].append(_clean_val(stripped[2:]))
                elif current_block == 'late-commands' and stripped.startswith('- '):
                    data['late_cmds'].append(_clean_val(stripped[2:]))
                elif current_block == 'snaps':
                    if stripped.startswith('- name:'):
                        if current_snap: data['snaps'].append(current_snap)
                        current_snap = {'name': _clean_val(line.split(':', 1)[1]), 'classic': False}
                    elif stripped.startswith('classic:'):
                        val = _clean_val(line.split(':', 1)[1]).lower()
                        current_snap['classic'] = (val == 'true' or val == 'yes')
                        
    if current_snap:
         data['snaps'].append(current_snap)
         
    return {"autoinstall": data, "x-os-overrides": overrides}

def run_os_prompts(config, os_name):
    shared_prompts = config.get('x-os-overrides', {}).get('shared', {}).get('prompts', [])
    os_prompts = config.get('x-os-overrides', {}).get(os_name, {}).get('prompts', [])
    
    if not shared_prompts and not os_prompts:
        return config
        
    selected_packages = []
    selected_cmds = []
    selected_snaps = []
    
    prompt_groups = []
    if shared_prompts: prompt_groups.append(("Global", shared_prompts))
    if os_prompts: prompt_groups.append((os_name.capitalize(), os_prompts))
        
    for group_name, prompts in prompt_groups:
        print_header(f"Dynamic Options: {group_name}")
        for p in prompts:
            print() # Padding
            target_dict = None
            if 'choices' in p and p['choices']:
                labels = [c['label'] for c in p['choices']]
                idx = ask_choice(p['ask'], labels, default=p.get('default'))
                target_dict = p['choices'][idx]
            else:
                if ask_yes_no(p['ask'], default=p.get('default', 'yes')):
                    target_dict = p
            
            if target_dict:
                selected_packages.extend(target_dict.get('packages', []))
                selected_cmds.extend(target_dict.get('late_cmds', []))
                selected_snaps.extend(target_dict.get('snaps', []))
                
                os_target = target_dict.get(os_name, {})
                selected_packages.extend(os_target.get('packages', []))
                selected_cmds.extend(os_target.get('late_cmds', []))
                selected_snaps.extend(os_target.get('snaps', []))
                
    ovr = config['x-os-overrides'].setdefault(os_name, {})
    ovr.setdefault('packages', []).extend(selected_packages)
    ovr.setdefault('late_cmds', []).extend(selected_cmds)
    ovr.setdefault('snaps', []).extend(selected_snaps)
    
    return config

def merge_os_overrides(config, os_name):
    data = config.get('autoinstall', {})
    ovr = config.get('x-os-overrides', {}).get(os_name, {})
    
    data.setdefault('packages', []).extend(ovr.get('packages', []))
    data.setdefault('late_cmds', []).extend(ovr.get('late_cmds', []))
    
    if 'snaps' in ovr:
        for s in ovr['snaps']:
            is_classic = '|classic' in s
            name = s.split('|')[0]
            data.setdefault('snaps', []).append({'name': name, 'classic': is_classic})
        
    config['autoinstall'] = data
    return config

def _inject_into_yaml(filepath, section, items, is_snaps=False):
    if not items: return
    with open(filepath, 'r') as f: lines = f.readlines()
    
    insert_idx = -1
    fallback_idx = -1
    in_autoinstall = False
    in_section = False
    
    for i, line in enumerate(lines):
        if line.startswith('autoinstall:'):
            in_autoinstall = True
        elif in_autoinstall:
            if line.strip() and not line.startswith(' '):
                in_autoinstall = False
                if fallback_idx == -1: fallback_idx = i
                continue
                
            if line.startswith(f'  {section}:'):
                in_section = True
                insert_idx = i + 1
            elif in_section:
                if line.startswith('    '):
                    insert_idx = i + 1
                elif line.strip() == '':
                    pass 
                else:
                    break
            elif not in_section:
                if line.startswith('  late-commands:') or line.startswith('  user-data:'):
                    if fallback_idx == -1: fallback_idx = i
                        
    if fallback_idx == -1: fallback_idx = len(lines)
        
    lines_to_inject = []
    for item in items:
        if is_snaps:
            if '|classic' in item:
                lines_to_inject.append(f"    - name: {item.split('|')[0]}\n      classic: true\n")
            else:
                lines_to_inject.append(f"    - name: {item}\n")
        else:
            lines_to_inject.append(f"    - {item}\n")
            
    if insert_idx == -1:
        lines_to_inject.insert(0, f"  {section}:\n")
        lines_to_inject.append("\n")
        insert_idx = fallback_idx
        
    lines.insert(insert_idx, "".join(lines_to_inject))
    with open(filepath, 'w') as f: f.writelines(lines)

def inject_yaml_snaps(filepath, items):
    _inject_into_yaml(filepath, 'snaps', items, is_snaps=True)

def inject_yaml_list(filepath, section, items):
    _inject_into_yaml(filepath, section, items, is_snaps=False)

def replace_in_file(filepath, pattern, replacement):
    with open(filepath, 'r') as f: content = f.read()
    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    with open(filepath, 'w') as f: f.write(content)