[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner-direct-single.svg)](https://stand-with-ukraine.pp.ua)
[![Made in Ukraine](https://img.shields.io/badge/made_in-Ukraine-ffd700.svg?labelColor=0057b7)](https://stand-with-ukraine.pp.ua)
[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/StandWithUkraine.svg)](https://stand-with-ukraine.pp.ua)
[![Russian Warship Go Fuck Yourself](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/RussianWarship.svg)](https://stand-with-ukraine.pp.ua)

<img src="media/icon.png" height="320">

# Update Checker

A Python utility for automatically checking and downloading updates for files and GitHub releases. It supports MD5 verification, automatic process management, and archive handling.

## Features

- Download and update files from URLs and GitHub releases
- MD5 checksum verification
- Automatic backup of existing files
- Process management (kill and relaunch capabilities)
- Archive extraction support
- Concurrent processing with thread pooling
- Configurable logging

## How it works
1. Reads configuration entries
2. For each entry:
   - Downloads file from URL or GitHub release
   - Verifies MD5 checksum if provided
   - Creates backup of existing file
   - Updates file if necessary
   - Handles process termination if file is locked
   - Extracts archives if specified
   - Launches/relaunches applications as configured

## Getting Started

- Create `updatechecker.yaml` in `%USERPROFILE%` or in the cloned repository folder from [updatechecker.example.yaml](updatechecker.example.yaml)
- Modify its values according to the examples

### Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/ALERTua/updatechecker.git
   ```
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 
3. Execute [updatechecker.cmd](updatechecker.cmd)
