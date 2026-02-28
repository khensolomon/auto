#!/bin/bash

# #############################################################################
# AUTOINSTALL GENERATOR & ISO PREPARER
# #############################################################################

# Color definitions for better UI
GREEN='\e[32m'
BLUE='\e[34m'
YELLOW='\e[33m'
RED='\e[31m'
BOLD='\e[1m'
NC='\e[0m' # No Color

info() { echo -e "${GREEN}${BOLD}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}${BOLD}[WARN]${NC} $1"; }
error() { echo -e "${RED}${BOLD}[ERROR]${NC} $1"; exit 1; }
header() {
    echo -e "${BLUE}========================================================${NC}"
    echo -e "${BLUE}${BOLD}   $1${NC}"
    echo -e "${BLUE}========================================================${NC}"
}

# Determine the actual user and their home directory (even if running with sudo)
REAL_USER=${SUDO_USER:-$USER}
if [ -n "$SUDO_USER" ]; then
    REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    REAL_HOME=$HOME
fi

# Get the directory where the script is actually located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

header "Step 1: Environment & Workspace Setup"

# Check for required tools
for tool in xorriso rsync openssl; do
    if ! command -v $tool &> /dev/null; then
        error "$tool is not installed. Please install it first (sudo apt install $tool)."
    fi
done

# 1. Prompt for Working Directory
DEFAULT_WORK_DIR="~/ubuntu-autoinstall"
read -p "$(echo -e "Enter working directory [$DEFAULT_WORK_DIR]: ")" WORK_DIR
WORK_DIR=${WORK_DIR:-$DEFAULT_WORK_DIR}
WORK_DIR="${WORK_DIR/#\~/$REAL_HOME}"

# Cleanup and setup workspace
if [ -d "$WORK_DIR" ]; then
    warn "Directory $WORK_DIR already exists."
    read -p "Clean up and recreate? (y/n) [y]: " CLEANUP
    CLEANUP=${CLEANUP:-y}
    if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
        info "Cleaning up old workspace..."
        sudo rm -rf "$WORK_DIR"
    fi
fi

info "Creating workspace structure in $WORK_DIR..."
mkdir -p "$WORK_DIR"/{mnt,extract/nocloud} || error "Failed to create directory."

header "Step 2: ISO Preparation"

# 2. Prompt for ISO file
DEFAULT_ISO="/mnt/keep/os/linux/Ubuntu/ubuntu-25.10-desktop-amd64.iso"
read -p "$(echo -e "Enter path to source Ubuntu ISO [$DEFAULT_ISO]: ")" ISO_PATH
ISO_PATH=${ISO_PATH:-$DEFAULT_ISO}
ISO_PATH="${ISO_PATH/#\~/$REAL_HOME}"

if [[ ! -f "$ISO_PATH" ]]; then
    error "ISO file not found at $ISO_PATH"
fi

# Mount and Extract ISO
info "Mounting ISO..."
sudo mount -o loop "$ISO_PATH" "$WORK_DIR/mnt" || error "Failed to mount ISO."

info "Extracting ISO content (this may take a minute)..."
rsync -a "$WORK_DIR/mnt/" "$WORK_DIR/extract/"

info "Unmounting source ISO..."
sudo umount "$WORK_DIR/mnt"

header "Step 3: Configuration & Customization"

# 3. Prompt for ubuntu.yaml location
DEFAULT_TEMPLATE="$SCRIPT_DIR/ubuntu.yaml"
read -p "$(echo -e "Enter path to ubuntu.yaml template [$DEFAULT_TEMPLATE]: ")" TEMPLATE_PATH
TEMPLATE_PATH=${TEMPLATE_PATH:-$DEFAULT_TEMPLATE}
TEMPLATE_PATH="${TEMPLATE_PATH/#\~/$REAL_HOME}"

if [[ ! -f "$TEMPLATE_PATH" ]]; then
    error "Template file not found at $TEMPLATE_PATH"
fi

# Basic validation
if ! grep -q "autoinstall:" "$TEMPLATE_PATH"; then
    error "The file does not appear to be a valid Ubuntu autoinstall YAML."
fi

# --- Extract defaults from the YAML file ---
info "Extracting default values from template..."

get_val() {
    grep "$1:" "$TEMPLATE_PATH" | head -n 1 | sed "s/.*$1:[[:space:]]*//;s/[\"']//g"
}

YAML_HOSTNAME=$(get_val "hostname")
YAML_LOCALE=$(get_val "locale")
YAML_LAYOUT=$(get_val "layout")
YAML_VARIANT=$(get_val "variant")
YAML_USER=$(get_val "username")
YAML_REALNAME=$(get_val "realname")

# 4. System Details Prompts
read -p "Enter Hostname [$YAML_HOSTNAME]: " NEW_HOSTNAME
NEW_HOSTNAME=${NEW_HOSTNAME:-$YAML_HOSTNAME}

echo -e "${BLUE}Hint:${NC} en_US.UTF-8, nb_NO.UTF-8"
read -p "Enter System Locale [$YAML_LOCALE]: " NEW_LOCALE
NEW_LOCALE=${NEW_LOCALE:-$YAML_LOCALE}

echo -e "${BLUE}Hint:${NC} 'no' (Norwegian), 'us' (English US)"
read -p "Enter Keyboard Layout [$YAML_LAYOUT]: " KYBD_LAYOUT
KYBD_LAYOUT=${KYBD_LAYOUT:-$YAML_LAYOUT}

read -p "Enter Keyboard Variant [$YAML_VARIANT]: " KYBD_VARIANT
KYBD_VARIANT=${KYBD_VARIANT:-$YAML_VARIANT}

read -p "Enter Username [$YAML_USER]: " NEW_USER
NEW_USER=${NEW_USER:-$YAML_USER}

read -p "Enter Real Name [$YAML_REALNAME]: " NEW_REALNAME
NEW_REALNAME=${NEW_REALNAME:-$YAML_REALNAME}

read -s -p "Enter New Password (blank to keep template hash): " PLAIN_PASSWORD
echo "" 

if [ -n "$PLAIN_PASSWORD" ]; then
    PASSWORD_HASH=$(openssl passwd -6 "$PLAIN_PASSWORD")
    UPDATE_PASS=true
else
    UPDATE_PASS=false
fi

header "Step 4: Generating Autoinstall Files"

info "Processing user-data..."
TEMP_USERDATA=$(mktemp)
cp "$TEMPLATE_PATH" "$TEMP_USERDATA"

sed -i "s/hostname: .*/hostname: $NEW_HOSTNAME/" "$TEMP_USERDATA"
sed -i "s/locale: .*/locale: $NEW_LOCALE/" "$TEMP_USERDATA"
sed -i "s/username: .*/username: $NEW_USER/" "$TEMP_USERDATA"
sed -i "s/realname: .*/realname: \"$NEW_REALNAME\"/" "$TEMP_USERDATA"
sed -i "s/layout: .*/layout: \"$KYBD_LAYOUT\"/" "$TEMP_USERDATA"
sed -i "s/variant: .*/variant: \"$KYBD_VARIANT\"/" "$TEMP_USERDATA"

if [ "$UPDATE_PASS" = true ]; then
    sed -i "s#password: .*#password: \"$PASSWORD_HASH\"#" "$TEMP_USERDATA"
fi

# Smart replace for the username in shell commands (e.g., 'su - username -c', 'usermod ... username')
# Using [[:space:]] boundaries ensures we don't accidentally modify URLs or file paths.
sed -E -i "s/([[:space:]])$YAML_USER([[:space:]]|$)/\1$NEW_USER\2/g" "$TEMP_USERDATA"
# Run a second time to catch any adjacent overlapping space-separated matches
sed -E -i "s/([[:space:]])$YAML_USER([[:space:]]|$)/\1$NEW_USER\2/g" "$TEMP_USERDATA"

mv "$TEMP_USERDATA" "$WORK_DIR/extract/nocloud/user-data"

info "Generating meta-data..."
cat <<EOF > "$WORK_DIR/extract/nocloud/meta-data"
instance-id: $NEW_HOSTNAME-autoinstall
local-hostname: $NEW_HOSTNAME
EOF

header "Step 5: Modifying Bootloader & Building ISO"

# Modify GRUB config
GRUB_CFG="$WORK_DIR/extract/boot/grub/grub.cfg"
info "Injecting Autoinstall entry into GRUB..."

if [ -f "$GRUB_CFG" ]; then
    # Ensure we have write permissions (extracted ISO files are read-only 0444 by default)
    chmod u+w "$GRUB_CFG"
    
    # We use a temporary file to construct the new GRUB config
    TEMP_GRUB=$(mktemp)
    
    # Define our new menu entry
    # Note: the \; is escaped for the shell, but GRUB needs the semicolon
    AUTOINSTALL_ENTRY="menuentry \"Ubuntu Autoinstall (Wipes Disk)\" {
        set gfxpayload=keep
        linux   /casper/vmlinuz  quiet splash autoinstall ds=nocloud\\\\;s=/cdrom/nocloud/ ---
        initrd  /casper/initrd
}"

    # Insert the entry before the first 'menuentry' found in the original file
    awk -v entry="$AUTOINSTALL_ENTRY" '/menuentry/ && !done { print entry; done=1 } 1' "$GRUB_CFG" > "$TEMP_GRUB"
    
    # Overwrite contents in-place instead of using 'mv', to bypass read-only directory permissions
    cat "$TEMP_GRUB" > "$GRUB_CFG"
    rm -f "$TEMP_GRUB"
    
    info "GRUB entry added successfully."
else
    warn "grub.cfg not found at $GRUB_CFG. Skipping bootloader modification."
fi

# Build the final ISO
ISO_FILENAME="$(basename "$ISO_PATH" .iso)-autoinstall.iso"
OUT_ISO="$WORK_DIR/$ISO_FILENAME"

info "Running xorriso to build final ISO..."
cd "$WORK_DIR" || error "Could not enter work directory."

# Execute xorriso
# We map the local nocloud directory and the modified grub.cfg into the ISO structure
sudo xorriso \
  -indev "$ISO_PATH" \
  -outdev "$OUT_ISO" \
  -boot_image any replay \
  -map "$WORK_DIR/extract/nocloud" /nocloud \
  -map "$GRUB_CFG" /boot/grub/grub.cfg

# Final Cleanup & Permissions
if [ -n "$SUDO_USER" ]; then
    sudo chown -R "$REAL_USER:$REAL_USER" "$WORK_DIR"
fi

header "Success!"
echo -e "1. Custom ISO:   ${GREEN}$OUT_ISO${NC}"
echo -e "2. Workspace:    ${GREEN}$WORK_DIR${NC}"
echo -e "--------------------------------------------------------"
info "Process complete. You can now flash $OUT_ISO to a USB drive."