#!/bin/bash
set -e

# --- Colors & UI Definitions ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

header() {
    echo -e "${BLUE}========================================================${NC}"
    echo -e "${BLUE}${BOLD}   $1${NC}"
    echo -e "${BLUE}========================================================${NC}"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

header "Debian Autoinstall Builder"

# --- 1. Prompt for Working Directory ---
DEFAULT_WORK_DIR="$HOME/debian-autoinstall"
echo -n -e "${YELLOW}Enter Working Directory [${DEFAULT_WORK_DIR}]: ${NC}"
read WORK_DIR
WORK_DIR=${WORK_DIR:-$DEFAULT_WORK_DIR}

# Cleanup and setup workspace
if [ -d "$WORK_DIR" ]; then
    warn "Directory $WORK_DIR already exists."
    echo -n -e "${YELLOW}Clean up and recreate? (y/n) [y]: ${NC}"
    read CLEANUP
    CLEANUP=${CLEANUP:-y}
    if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
        info "Cleaning up old workspace..."
        sudo rm -rf "$WORK_DIR"
    fi
fi

# Ensure the working directory exists early on
mkdir -p "$WORK_DIR"

# --- 2. Prompt for YAML Configuration ---
DEFAULT_YAML="$SCRIPT_DIR/ubuntu.yaml"
echo -n -e "${YELLOW}Enter ubuntu.yaml path [${DEFAULT_YAML}]: ${NC}"
read YAML_PATH
YAML_PATH=${YAML_PATH:-$DEFAULT_YAML}

if [ ! -f "$YAML_PATH" ]; then
    error "Configuration file not found at '$YAML_PATH'."
fi

# --- 3. Prompt for Source ISO & Validate ---
DEFAULT_ISO="/mnt/keep/os/linux/Debian/debian-12.10.0-amd64-netinst.iso"
echo -n -e "${YELLOW}Enter Source ISO Path [${DEFAULT_ISO}]: ${NC}"
read ISO_PATH
ISO_PATH=${ISO_PATH:-$DEFAULT_ISO}

if [ ! -f "$ISO_PATH" ]; then
    error "Source ISO not found at '$ISO_PATH'."
fi

# Basic validation: Check if the filename contains 'debian'
if ! basename "$ISO_PATH" | grep -qi "debian"; then
    error "The file '$ISO_PATH' does not appear to be a valid Debian ISO (filename must contain 'debian')."
fi

echo -e "${BLUE}-----------------------------------${NC}"
info "Using Base ISO: $ISO_PATH"
info "Using YAML Config: $YAML_PATH"
info "Using Work Dir: $WORK_DIR"
echo -e "${BLUE}-----------------------------------${NC}"

# --- 4. Extract Defaults from YAML & Prompt for Inputs ---
# Parse the yaml for hostname, username, and realname
DEFAULT_HOST=$(grep -E "^[[:space:]]*hostname:" "$YAML_PATH" | awk -F ':' '{print $2}' | tr -d " \"'\r")
DEFAULT_USER=$(grep -E "^[[:space:]]*username:" "$YAML_PATH" | awk -F ':' '{print $2}' | tr -d " \"'\r")

# For realname, use sed to strip leading/trailing spaces and surrounding quotes so internal spaces are preserved
DEFAULT_REALNAME=$(grep -E "^[[:space:]]*realname:" "$YAML_PATH" | awk -F ':' '{print $2}' | sed -e 's/\r//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")

# Fallbacks just in case the YAML doesn't have these fields
DEFAULT_HOST=${DEFAULT_HOST:-debian-mini}
DEFAULT_USER=${DEFAULT_USER:-khensolomon}
DEFAULT_REALNAME=${DEFAULT_REALNAME:-User}

echo -n -e "${YELLOW}Enter Target Hostname [${DEFAULT_HOST}]: ${NC}"
read NEW_HOST
NEW_HOST=${NEW_HOST:-$DEFAULT_HOST}

echo -n -e "${YELLOW}Enter Target Username [${DEFAULT_USER}]: ${NC}"
read NEW_USER
NEW_USER=${NEW_USER:-$DEFAULT_USER}

echo -n -e "${YELLOW}Enter Target Real Name [${DEFAULT_REALNAME}]: ${NC}"
read NEW_REALNAME
NEW_REALNAME=${NEW_REALNAME:-$DEFAULT_REALNAME}

# Read password silently (-s) so it doesn't show on screen
echo -n -e "${YELLOW}Enter Password for $NEW_USER (blank to keep template hash): ${NC}"
read -s NEW_PASS
echo

if [ -n "$NEW_PASS" ]; then
    # Hash password securely and export it as an environment variable for Python
    info "Hashing new password securely..."
    export PRESEED_PASSWORD_HASH=$(openssl passwd -6 "$NEW_PASS")
else
    info "Keeping existing password hash from template..."
    unset PRESEED_PASSWORD_HASH
fi

# --- 5. Generate Preseed File directly into WORK_DIR ---
info "Generating preseed.cfg from $YAML_PATH..."
python3 "$SCRIPT_DIR/generate_preseed.py" \
    --yaml "$YAML_PATH" \
    --out "$WORK_DIR/preseed.cfg" \
    --hostname "$NEW_HOST" \
    --username "$NEW_USER" \
    --realname "$NEW_REALNAME"

# --- 6. Setup Extraction Directory ---
rm -rf "$WORK_DIR/extract" "$WORK_DIR/mnt"
mkdir -p "$WORK_DIR/extract/boot/grub" "$WORK_DIR/extract/isolinux" "$WORK_DIR/mnt"

# --- 7. Mount ISO & Extract Bootloader Config ---
# Only extracting what we need to modify!
info "Extracting GRUB and ISOLINUX configurations..."
sudo mount -o loop "$ISO_PATH" "$WORK_DIR/mnt" >/dev/null 2>&1
cp "$WORK_DIR/mnt/boot/grub/grub.cfg" "$WORK_DIR/extract/boot/grub/grub.cfg"

# Extract ISOLINUX menu config if present (Used for Legacy BIOS Boot)
if [ -f "$WORK_DIR/mnt/isolinux/menu.cfg" ]; then
    cp "$WORK_DIR/mnt/isolinux/menu.cfg" "$WORK_DIR/extract/isolinux/menu.cfg"
    chmod u+w "$WORK_DIR/extract/isolinux/menu.cfg"
fi

sudo umount "$WORK_DIR/mnt" >/dev/null 2>&1
chmod u+w "$WORK_DIR/extract/boot/grub/grub.cfg"

# --- 8. Modify GRUB (for UEFI Boot) ---
info "Injecting Autoinstall entry into Debian GRUB (UEFI)..."
GRUB_CFG="$WORK_DIR/extract/boot/grub/grub.cfg"
TEMP_GRUB=$(mktemp)

# Note: Debian's kernel path and parameters are slightly different from Ubuntu's
DEBIAN_ENTRY="menuentry \"Debian Autoinstall (Wipes Disk)\" {
    set gfxpayload=keep
    linux    /install.amd/vmlinuz auto=true priority=critical preseed/file=/cdrom/preseed.cfg --- quiet
    initrd   /install.amd/initrd.gz
}"

# Insert our custom entry before the first existing menuentry
awk -v entry="$DEBIAN_ENTRY" '/menuentry/ && !done { print entry; done=1 } 1' "$GRUB_CFG" > "$TEMP_GRUB"
cat "$TEMP_GRUB" > "$GRUB_CFG"
rm -f "$TEMP_GRUB"

# --- 8b. Modify ISOLINUX (for Legacy BIOS Boot) ---
ISOLINUX_CFG="$WORK_DIR/extract/isolinux/menu.cfg"
if [ -f "$ISOLINUX_CFG" ]; then
    info "Injecting Autoinstall entry into ISOLINUX main menu (Legacy BIOS)..."
    TEMP_ISO=$(mktemp)
    
    DEBIAN_ISO_ENTRY="label autoinstall
    menu label ^Debian Autoinstall (Wipes Disk)
    kernel /install.amd/vmlinuz
    append auto=true priority=critical vga=788 initrd=/install.amd/initrd.gz preseed/file=/cdrom/preseed.cfg --- quiet
"
    
    # Insert our custom entry immediately after the standard menu includes
    # This guarantees it appears as the absolute FIRST option on the screen.
    awk -v entry="$DEBIAN_ISO_ENTRY" '/^include stdmenu\.cfg/ && !done { print $0; print entry; done=1; next } 1' "$ISOLINUX_CFG" > "$TEMP_ISO"
    cat "$TEMP_ISO" > "$ISOLINUX_CFG"
    rm -f "$TEMP_ISO"
fi

# --- 9. Rebuild ISO using xorriso safe patch method ---
ORG_ISO_NAME=$(basename "$ISO_PATH")
ORG_ISO_BASE="${ORG_ISO_NAME%.*}"
TARGET_ISO="$WORK_DIR/${ORG_ISO_BASE}-autoinstall.iso"
info "Rebuilding ISO: $TARGET_ISO"

# We use a Bash array to handle dynamic xorriso mapping arguments safely
XORRISO_ARGS=(
  -indev "$ISO_PATH"
  -outdev "$TARGET_ISO"
  -boot_image any replay
  -map "$WORK_DIR/preseed.cfg" /preseed.cfg
  -map "$WORK_DIR/extract/boot/grub/grub.cfg" /boot/grub/grub.cfg
)

# If ISOLINUX existed and we patched it, append the map command to xorriso
if [ -f "$ISOLINUX_CFG" ]; then
    XORRISO_ARGS+=( -map "$ISOLINUX_CFG" /isolinux/menu.cfg )
fi

# Execute xorriso with our constructed arguments
xorriso "${XORRISO_ARGS[@]}" >/dev/null 2>&1

echo -e "${BLUE}-----------------------------------${NC}"
success "Debian Autoinstall ISO created successfully!"
info "Output: $TARGET_ISO"