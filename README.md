# BLE_Direwolf_Bridge
This is a Python script that runs on a Raspberry Pi Zero 2W and bridges between BLE and the Direwolf software TNC. 

RadioMail, Packet Commander, and the APRS.fi app running on iOS are able to use the bridge and send and receive packets. 

I used the Claude LLM to create this script. There was no single prompt that created this, it was a back and forth of trying things, and almost giving up, trying more things, modifying code and uploading and having Claude base future versions on my edits, and eventually arriving at something that worked. I also tried DeepSeek, but what it generated was gargabe: It had function signatures wrong, had missing arguments and other issues that made it not worth even considering its code for this type of iterative project. 

This was my first serious attempt at having an LLM help with software development. 

## Preparing Raspberry Pi Zero 2W
I prepared a microSD card with the 32bit version of Raspberry Pi OS Lite Trixie. Once the OS booted, I ran the following commands:

sudo apt update
sudo apt upgrade
sudo apt install cmake libgps-dev libhamlib-dev libudev-dev libasound2-dev git
git clone https://www.github.com/wb2osz/direwolf
cd direwolf
mkdir build
cd build
cmake ..
make -j4
sudo make install

## Running Direwolf and the Bridge

At this point, edit the ~/direwolf.conf file (a sample lives in direwolf/build/direwolf.conf). 

Direwolf and the BLE_Direwolf_Bridge.py script communicate via the /tmp/kisstnc link to a pseudo terminal that Direwolf creates. For this to work, we need to start Direwolf with the -p arguments:

direwolf -p

We can now start the script:

python3 ble_direwolf_bridge.py

Both Direwolf and the script will produce debug output. 

Connect to Pi using e.g. RadioMail by selecting the KISS TNC in Settings>Packet KISS TNC Modem>Default TNC - the bridge should be shown under BLE KISS TNC - Audo discovered. 


