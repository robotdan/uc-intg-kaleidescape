# Kaleidescape Integration for Unfolded Circle Remotes

[![GitHub Release](https://img.shields.io/github/v/release/robotdan/uc-intg-kaleidescape?style=flat-square)](https://github.com/robotdan/uc-intg-kaleidescape/releases)
![License](https://img.shields.io/badge/license-MPL--2.0-blue?style=flat-square)
[![GitHub issues](https://img.shields.io/github/issues/robotdan/uc-intg-kaleidescape?style=flat-square)](https://github.com/robotdan/uc-intg-kaleidescape/issues)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/robotdan/uc-intg-kaleidescape/total?style=flat-square)

Control your **Kaleidescape Video Player** directly from your Unfolded Circle Remote Two or Remote 3. A media player and remote entity are exposed to the Remote core.

> **Note:** At this time only one player is supported. If you have multiple players, either remove the other players from the network while configuring the one you want, or use manual setup.


## Supported media player attributes

- POWER STATES (On, Off, Unknown)
- MEDIA DURATION
- MEDIA IMAGE_URL
- MEDIA POSITION
- MEDIA POSITION_UPDATED_AT
- MEDIA TITLE
- MEDIA TYPE

## Supported **remote** UI:

- Power on
- Power off
- Directional pad
- Back
- Menu
- Previous
- Play / Pause
- Play
- Pause
- Stop
- Next
- Fast Forward
- Rewind
- Movie Collections
- Movie Covers
- Movie List
- Movie Store
- Search
- Shuffle
- Subtitles
- Alphabetize
- Intermission
- Cancel
- Page Up
- Page Down
- Replay

## Installation

### Run on the remote as a custom integration driver

#### 1 - Download Integration Driver
Download the uc-intg-kaleidescape-x.x.x-aarch64.tar.gz archive in the assets section from the [latest release](https://github.com/robotdan/uc-intg-kaleidescape/releases/latest).

#### 2 - Upload & Installation
Upload in the Web Configurator
Go to Integrations in the top menu. On the top right click on Add new/Install custom and choose the downloaded tar.gz file.

#### 3 - Configuration
Click on the Integration to run setup. The player should be found automatically, if not use the manual setup.

#### 4 - Updating
First remove the existing version by clicking the delete icon on the integration, this needs to be done twice. The first time deletes the configuration, the second time fully removes it. Then repeat the above steps.

### Run on a local server
The are instructions already provided by unfolded circle in their included integrations.

## Credits
This Integration uses the [pykaleidescape](https://github.com/SteveEasley/pykaleidescape) library written by Steve Easley

## License

Licensed under the [**Mozilla Public License 2.0**](https://choosealicense.com/licenses/mpl-2.0/).  
See [LICENSE](LICENSE) for more details.
