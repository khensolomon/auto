#!/usr/bin/env python3

"""
Ubuntu Environment Interactive Setup Script

Version: 1.0.0
Date: 2026-03-04

Description:
    An interactive, data-driven script to configure a fresh Ubuntu environment.
    Designed to be executed directly from a URL or run locally. Supports external 
    JSON configuration injection via the '--tasks' argument.
    
Changelog:
    - 1.0.0 (2026-03-04): Initial stable release featuring APT package installation, 
                          URL script execution, autostart entries, GNOME dock configuration,
                          smart JSON task merging, and action logging for easy rollbacks.
"""

import os
import sys
import subprocess
import urllib.request
import json
import datetime
import argparse

# ==========================================
# 0. TERMINAL FIX FOR PIPED EXECUTION
# ==========================================
if not sys.stdin.isatty():
    sys.stdin = open('/dev/tty')

# ==========================================
# 1. CONFIGURATION DATA
# ==========================================
SETUP_TASKS = [
    {
        "name": "Required Applications",
        "prompt": "Check and install missing required applications?",
        "type": "apt_packages",
        "packages": [
            "inkscape", "gimp", "audacity", 
            "sqlitebrowser", "curl", "wget", 
            "gpg", "openssh-server"
        ]
    },
    {
        "name": "GNOME Extension",
        "prompt": "Install custom GNOME extension 'lesion'?",
        "type": "python_url",
        "url": "https://raw.githubusercontent.com/khensolomon/lesion/master/install.py",
    },
    {
        "name": "Autostart Applications",
        "prompt": "Configure autostart applications?",
        "type": "autostart_group",
        "items": [
            {
                "app_name": "Visual Studio Code",
                "filename": "vscode.desktop",
                "content": [
                    "[Desktop Entry]",
                    "Type=Application",
                    "Exec=code",
                    "Hidden=false",
                    "NoDisplay=false",
                    "X-GNOME-Autostart-enabled=true",
                    "Name=Visual Studio Code",
                    "Comment=Start VS Code on login"
                ]
            },
            {
                "app_name": "Remmina",
                "filename": "remmina.desktop",
                "content": [
                    "[Desktop Entry]",
                    "Type=Application",
                    "Exec=remmina -i",
                    "Hidden=false",
                    "NoDisplay=false",
                    "X-GNOME-Autostart-enabled=true",
                    "Name=Remmina",
                    "Comment=Start Remmina on login"
                ]
            },
            {
                "app_name": "SSH Agent",
                "filename": "ssh-agent.desktop",
                "content": [
                    "[Desktop Entry]",
                    "Type=Application",
                    "Exec=ssh-agent",
                    "Hidden=false",
                    "NoDisplay=false",
                    "X-GNOME-Autostart-enabled=true",
                    "Name=SSH Agent",
                    "Comment=Start SSH Agent on login"
                ]
            }
        ]
    },
    {
        "name": "GNOME Dock Configuration",
        "prompt": "Change GNOME panel to a floating dock?",
        "type": "gnome_dock_interactive"
    }
]

# ==========================================
# 2. LOGGER SYSTEM (For Verification & Rollback)
# ==========================================
LOG_FILE = os.path.expanduser("~/.ubuntu_setup_history.json")

def log_action(action_data):
    """Appends structured data to the local history JSON file."""
    history = []
    
    # Load existing history if the file exists
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                history = json.load(f)
        except json.JSONDecodeError:
            pass # File is corrupt or empty, start fresh

    # Add timestamp to the new action
    action_data["timestamp"] = datetime.datetime.now().isoformat()
    history.append(action_data)

    # Save it back to the disk
    try:
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f, indent=4)
    except IOError as e:
        print_error(f"Failed to write to log file: {e}")

# ==========================================
# 3. UI & FORMATTING HELPERS
# ==========================================
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")

def print_step(text):
    print(f"\n{Colors.OKBLUE}{Colors.BOLD}==> {text}{Colors.ENDC}")

def print_info(text, indent=1):
    spacing = "  " * indent
    print(f"{spacing}{text}")

def print_success(text, indent=1):
    spacing = "  " * indent
    print(f"{spacing}{Colors.OKGREEN}[✓] {text}{Colors.ENDC}")

def print_error(text, indent=1):
    spacing = "  " * indent
    print(f"{spacing}{Colors.FAIL}[✗] {text}{Colors.ENDC}")

def ask_yes_no(question, default="y", indent=1):
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    prompt_hint = " [Y/n] " if default == "y" else " [y/N] "
    spacing = "  " * indent

    while True:
        print(f"{spacing}{Colors.WARNING}? {question}{prompt_hint}{Colors.ENDC}", end="")
        try:
            choice = input().lower()
        except EOFError:
            print_error("\nInput stream detached. Cannot read user input.")
            sys.exit(1)
            
        if choice == "":
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            print_info("Please respond with 'yes' or 'no' (or 'y' or 'n').", indent + 1)

def ask_choice(question, choices, indent=1):
    spacing = "  " * indent
    print(f"{spacing}{Colors.WARNING}? {question}{Colors.ENDC}")
    
    for i, choice in enumerate(choices, 1):
        print_info(f"{i}. {choice.capitalize()}", indent + 1)
    
    while True:
        print(f"{spacing}{Colors.WARNING}Select an option [1-{len(choices)}]: {Colors.ENDC}", end="")
        try:
            answer = int(input())
            if 1 <= answer <= len(choices):
                return choices[answer - 1]
            else:
                print_info(f"Please enter a number between 1 and {len(choices)}.", indent + 1)
        except ValueError:
            print_info("Please enter a valid number.", indent + 1)
        except EOFError:
            print_error("\nInput stream detached. Cannot read user input.")
            sys.exit(1)

def ensure_sudo(reason="Administrative privileges are required for this step.", indent=2):
    print_info(reason, indent)
    try:
        subprocess.run(['sudo', '-v'], check=True)
    except subprocess.CalledProcessError:
        print_error("Failed to acquire sudo privileges. Exiting to prevent partial setup.", indent)
        sys.exit(1)
    except KeyboardInterrupt:
        print_error("\nSetup aborted by user.", indent)
        sys.exit(1)

# Helper for gsettings Rollback data
def get_current_gsetting(schema, key):
    try:
        result = subprocess.run(['gsettings', 'get', schema, key], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

# ==========================================
# 4. TASK RUNNERS (The Core Logic)
# ==========================================
def run_python_url(task):
    print_info("Fetching and running script...")
    try:
        with urllib.request.urlopen(task["url"]) as response:
            script_content = response.read()
        
        subprocess.run(['python3', '-'], input=script_content, check=True)
        print_success(f"Successfully executed script from {task['url']}")
        
        # Log this action
        log_action({
            "task_name": task["name"],
            "type": "python_script_execution",
            "url_executed": task["url"],
            "note": "External scripts must be uninstalled manually if required."
        })
    except Exception as e:
        print_error(f"Failed to execute script: {e}")

def run_autostart_group(task):
    autostart_dir = os.path.expanduser("~/.config/autostart")
    os.makedirs(autostart_dir, exist_ok=True)
    
    created_files = []

    for item in task["items"]:
        if ask_yes_no(f"Add {item['app_name']} to autostart?", default="y", indent=2):
            filepath = os.path.join(autostart_dir, item["filename"])
            try:
                with open(filepath, 'w') as f:
                    clean_content = "\n".join(item["content"]) + "\n"
                    f.write(clean_content)
                print_success(f"Created {item['filename']}", indent=2)
                created_files.append(filepath)
            except IOError as e:
                print_error(f"Failed to create {item['filename']}: {e}", indent=2)
        else:
            print_info(f"Skipping {item['app_name']}.", indent=2)
            
    if created_files:
        log_action({
            "task_name": task["name"],
            "type": "files_created",
            "files": created_files
        })

def run_gnome_dock_interactive(task):
    schema = 'org.gnome.shell.extensions.dash-to-dock'
    
    # 1. Ask user for input
    position = ask_choice("Where do you want the dock positioned?", ["BOTTOM", "LEFT", "RIGHT", "TOP"])
    
    # 2. Gather previous state for the log BEFORE changing anything
    rollback_data = [
        {"schema": schema, "key": "extend-height", "previous_value": get_current_gsetting(schema, 'extend-height')},
        {"schema": schema, "key": "dock-fixed", "previous_value": get_current_gsetting(schema, 'dock-fixed')},
        {"schema": schema, "key": "dock-position", "previous_value": get_current_gsetting(schema, 'dock-position')}
    ]

    # 3. Apply the new commands
    cmds = [
        ['gsettings', 'set', schema, 'extend-height', 'false'],
        ['gsettings', 'set', schema, 'dock-fixed', 'true'],
        ['gsettings', 'set', schema, 'dock-position', f"'{position}'"]
    ]

    for cmd in cmds:
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print_error(f"Failed to execute '{' '.join(cmd)}': {e}")
            return
            
    # 4. Save the exact rollback commands to the log
    log_action({
        "task_name": task["name"],
        "type": "gsettings_modified",
        "rollback_instructions": rollback_data
    })
    
    print_success("Dock configured successfully.")

def run_apt_packages(task):
    packages = task.get("packages", [])
    if not packages:
        return

    missing_packages = []
    print_info("Checking package status...")
    
    for pkg in packages:
        result = subprocess.run(['dpkg', '-s', pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            print_success(f"{pkg} is already installed.", indent=2)
        else:
            print_error(f"{pkg} is NOT installed.", indent=2)
            missing_packages.append(pkg)
            
    if not missing_packages:
        print_success("All required packages are already installed!", indent=2)
        return

    choices = [
        f"Install all {len(missing_packages)} missing packages",
        "Ask to install each missing package individually",
        "Skip package installation"
    ]
    choice = ask_choice("How would you like to handle the missing packages?", choices, indent=2)
    
    packages_to_install = []
    
    if choice == choices[0]:
        packages_to_install = missing_packages
    elif choice == choices[1]:
        for pkg in missing_packages:
            if ask_yes_no(f"Install {pkg}?", default="n", indent=3):
                packages_to_install.append(pkg)

    if packages_to_install:
        ensure_sudo(reason=f"Sudo is required to install {len(packages_to_install)} package(s).", indent=2)
        print_info("Updating package list and installing...", indent=2)
        try:
            subprocess.run(['sudo', 'apt-get', 'update'], check=True)
            subprocess.run(['sudo', 'apt-get', 'install', '-y'] + packages_to_install, check=True)
            print_success("Packages installed successfully.", indent=2)
            
            # Log ONLY the packages we actively installed today, not the ones that were already there
            log_action({
                "task_name": task["name"],
                "type": "apt_installed",
                "packages_installed": packages_to_install
            })
        except subprocess.CalledProcessError as e:
            print_error(f"Failed to install packages: {e}", indent=2)
    else:
        print_info("Skipping package installation.", indent=2)

# Map task types to their runner functions
TASK_HANDLERS = {
    "python_url": run_python_url,
    "autostart_group": run_autostart_group,
    "gnome_dock_interactive": run_gnome_dock_interactive,
    "apt_packages": run_apt_packages
}


# ==========================================
# 5. MAIN ENGINE & MERGE LOGIC
# ==========================================
def merge_tasks(default_tasks, custom_tasks):
    """Merges custom tasks into defaults. Overrides by 'name', or appends if new."""
    merged = []
    # Create a dictionary of custom tasks keyed by their name for easy lookup
    custom_dict = {t['name']: t for t in custom_tasks if 'name' in t}
    
    # 1. Update existing default tasks or keep them
    for task in default_tasks:
        if task['name'] in custom_dict:
            merged.append(custom_dict.pop(task['name'])) # Override with user custom task
        else:
            merged.append(task) # Keep default task
            
    # 2. Append any brand new custom tasks that weren't in the defaults
    for task in custom_dict.values():
        merged.append(task)
        
    return merged

def main():
    # --- Parse Command Line Arguments ---
    parser = argparse.ArgumentParser(description="Ubuntu Environment Interactive Setup Script")
    parser.add_argument('--tasks', type=str, help="Path to a custom JSON file to merge tasks.", default=None)
    args = parser.parse_args()

    # --- Determine Final Tasks List ---
    final_tasks = SETUP_TASKS
    if args.tasks:
        if os.path.exists(args.tasks):
            try:
                with open(args.tasks, 'r') as f:
                    user_tasks = json.load(f)
                if isinstance(user_tasks, list):
                    final_tasks = merge_tasks(SETUP_TASKS, user_tasks)
                    print_success(f"Successfully loaded and merged custom tasks from {args.tasks}", indent=0)
                else:
                    print_error("Custom tasks file must contain a JSON list. Using defaults.", indent=0)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in {args.tasks}: {e}. Using defaults.", indent=0)
        else:
            print_error(f"Custom tasks file not found: {args.tasks}. Using defaults.", indent=0)

    print_header("Ubuntu Environment Interactive Setup Script")
    print_info("Running configuration...\n", indent=0)

    # --- Pre-flight Review ---
    print_step("Pre-flight Review")
    print_info("This script is configured to offer the following setup tasks:", indent=1)
    for i, task in enumerate(final_tasks, 1):
        print_info(f"{i}. {task['name']}", indent=2)
    
    print_info("\nYou will be prompted for permission before any changes are made.", indent=1)
    if not ask_yes_no("Do you want to proceed with the setup wizard?", default="y", indent=1):
        print_info("Setup safely aborted by user.", indent=1)
        return

    # --- Task Execution ---
    for task in final_tasks:
        print_step(task["name"])
        
        if ask_yes_no(task["prompt"]):
            handler = TASK_HANDLERS.get(task["type"])
            if handler:
                handler(task)
            else:
                print_error(f"Unknown task type: {task['type']}")
        else:
            print_info(f"Skipping {task['name'].lower()}.", indent=1)

    print_step("Setup Complete")
    print_success(f"A detailed history of changes was saved to: {LOG_FILE}", indent=1)
    print_info("Please log out and log back in for all changes to take full effect.\n", indent=0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_error("\n\nSetup aborted manually by user.")
        sys.exit(1)