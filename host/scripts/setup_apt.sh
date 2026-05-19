#!/usr/bin/env bash
# Install apt packages required for host setup on Raspberry Pi OS Bookworm.
# - pyenv build dependencies (so Python 3.13.x can be compiled from source)
# - libusb / python3-dev for PaSoRi (also covered by setup_nfc.sh)
#
# Run from anywhere:
#   sudo bash host/scripts/setup_apt.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash host/scripts/setup_apt.sh" >&2
  exit 1
fi

echo "==> apt update"
apt-get update

echo "==> Installing apt packages"
apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  git \
  wget \
  libssl-dev \
  zlib1g-dev \
  libbz2-dev \
  libreadline-dev \
  libsqlite3-dev \
  libncursesw5-dev \
  xz-utils \
  tk-dev \
  libxml2-dev \
  libxmlsec1-dev \
  libffi-dev \
  liblzma-dev \
  llvm \
  libusb-1.0-0 \
  libusb-1.0-0-dev \
  libpcsclite-dev \
  python3-dev \
  sqlite3

echo
echo "Done."
