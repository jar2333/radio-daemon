#import hashlib
import xml.etree.ElementTree as ET
import datetime
import time
import os
import shutil 
import subprocess
import signal
import mutagen
import imghdr
import sys
from random import shuffle

import logging

DAEMON_DIR = "/home/elaine/app/source_daemon"

# USER_CONFIG_PATH = "user-config.xml"
USER_CONFIG_PATH = sys.argv[1]

logging.basicConfig(level=logging.DEBUG, filename=f"{DAEMON_DIR}/log/app.log")

def to_pcm(file_path):
    #hardcoded: sample rate 44100, channels 2. IceS expects these two values (specified in ices.xml)
    cmd = ["ffmpeg", "-i", file_path, "-ar", "44100", "-ac", "2", "-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-"]

    ffmpeg_process = subprocess.run(cmd, capture_output=True)

    return ffmpeg_process.stdout

def update_metadata_file(track_metadata, ices_process):
    #add accessed metadata, sensitive to when this file is written!
    track_metadata['accessed'] = str(datetime.datetime.now(datetime.timezone.utc))

    with open(f"{DAEMON_DIR}/tmp/metadata.txt", 'w') as f:
        f.write("\n".join([f"{key}={track_metadata[key]}" for key in track_metadata]))

    #send signal to ices process that metadata.txt updated     
    ices_process.send_signal(signal.SIGUSR1)    

def update_image_file(dir, album_metadata):
    image_file = album_metadata['image']
    shutil.copy(f"{dir}/{image_file}", f"{DAEMON_DIR}/tmp/current")

def get_file_metadata(file_path):
    f = mutagen.File(file_path)
    if f is None: #if not audio/failed
        return None
    d = dict(f.tags)

    tags = {k : d[k][0] for k in d} #make it not return a (key, singleton list) pair?
    length = f.info.length

    #add filename to tags:
    filename = file_path.split('/')[-1]
    tags['filename'] = filename

    return (tags, length)

def create_track_metadata(file_metadata, album_metadata, slot):
    tags, length = file_metadata

    track_metadata = dict(album_metadata) #copy
    for key in tags:
        if not key in track_metadata:
            track_metadata[key] = tags[key]

    if not 'title' in track_metadata:
        track_metadata['title'] = track_metadata['filename']
    track_metadata['length']   = str(length)
    track_metadata['genre']    = slot.genre #can be changed to general album metadata later

    return track_metadata

class TimeSlot:
    def __init__(self, start, end, genre):
        self.start = start
        self.end   = end
        self.genre = genre
        self.albums = []

    #automatically detects and stores the absolute path, image, and track list
    def add_album(self, dir, album_metadata):
        #for counting album duration
        # album_length = 0

        #get all tracks (sorted by filename!)
        track_filenames = sorted(os.listdir(dir))

        tracks = []
        for fn in track_filenames:
            file_path = f"{dir}/{fn}"

            #get file metadata
            file_metadata = get_file_metadata(file_path)
            if file_metadata is None: #if not audio/failed, skip
                continue

            tags, length = file_metadata

            #update album length
            # album_length += length

            #create track metadata
            track_metadata = create_track_metadata(file_metadata, album_metadata, self)

            tracks.append((file_path, track_metadata))

        #auto find image file
        image_file = None
        file_type = None
        for file in os.listdir(dir):
            file_type = imghdr.what(f"{dir}/{file}")
            if file_type:
                image_file = file
                break

        #set image album metadata
        album_metadata['image'] = image_file

        self.albums.append((dir, tracks, album_metadata))

#brittle, but it works...
def parse_slots():
    slots = []

    #read config
    tree = ET.parse(USER_CONFIG_PATH)
    root = tree.getroot()

    #parse slots
    for slot in root.findall('timeslot'):
        start  = datetime.time.fromisoformat(slot.find('time').find('start').text)
        end    = datetime.time.fromisoformat(slot.find('time').find('end').text)
        genre  = slot.find('genre').text.strip()

        s = TimeSlot(start, end, genre)

        #parse path to find album dirs
        albums_path = os.path.expanduser(slot.find('albums').text.strip())

        #parse blacklisted album dirs
        blacklisted = {e.text.strip() for e in slot.find('blacklist').findall('album')}

        #add albums to slot in randomized order
        album_directories = os.listdir(albums_path)
        shuffle(album_directories)

        for album_dir in album_directories:
            if not album_dir in blacklisted:
                path = f"{albums_path}/{album_dir}"
                # metadata_elements = [album.find(t) for t in ['title', 'artist', 'year']]
                # metadata = {e.tag : e.text.strip() for e in metadata_elements if not (e is None)}
                s.add_album(path, {})

        slots.append(s)

    for s in slots:
        for dir, tracks, album_metadata in s.albums:
            logging.debug(f"parsed album: {dir.split('/')[-1]}")

    #sort wrt start time (valid asumming slots don't overlap!) 
    #would be useful to add a check for this!
    slots.sort(key=lambda s: s.start)

    return slots

def get_remaining_seconds(slot):
    current       = datetime.datetime.now()
    end_delta     = datetime.timedelta(hours=slot.end.hour, minutes=slot.end.minute)
    current_delta = datetime.timedelta(hours=current.hour, minutes=current.minute)

    return (end_delta.total_seconds() - current_delta.total_seconds()) % 86400 #seconds in 24 hours!

def get_seconds_to_start(current_date, slot):
    start_delta   = datetime.timedelta(hours=slot.start.hour, minutes=slot.start.minute)
    current_delta = datetime.timedelta(hours=current_date.hour, minutes=current_date.minute)

    return (start_delta.total_seconds() - current_delta.total_seconds()) % 86400 #seconds in 24 hours!

#assumes slots are ordered in time
def find_current_slot(slots, offset):
    current_date = datetime.datetime.now()

    nearest_seconds_to_start = 86400
    nearest_index = -1
    for i in range(len(slots)):
        seconds_to_start = get_seconds_to_start(current_date, slots[i])
        if seconds_to_start <= nearest_seconds_to_start:
            nearest_seconds_to_start = seconds_to_start
            nearest_index = i

    if offset:    
        return slots[(nearest_index+1) % len(slots)]

    return slots[nearest_index]
    
def has_day_passed(album_play_date):
    return (datetime.datetime.now() - album_play_date).total_seconds() >= 86400
#slots (defined by user-config.xml)
#--albums (directory)
#----songs (files)

#things to update, and when:
# change slot  -> new genre -> update metadata.txt
# change album -> new album title, album artist, album year -> update metadata.txt
# change song  -> new song title, song artist, song year -> update metadata.txt

slots = parse_slots()
last_edited = os.path.getmtime(USER_CONFIG_PATH)

#key=path, value=date_played
#check if not here OR 24 hours have passed before playing
#use bool flag to indicate if a slot got to play any albums
#if not, sleep, wait for config changes lol
ALBUM_BLACKLIST = dict()

#start ices stream (CONSTANT)
ices_process = subprocess.Popen(['ices', f'{DAEMON_DIR}/config/ices.xml'], 
                                stdin=subprocess.PIPE, 
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
logging.debug("Initializing IceS...")
time.sleep(3)
logging.debug("IceS started.")

try:
    offset = False
    while True:
        restart = False #flag initialize

        logging.debug("Finding time slot...")
        #find currently applicable slot
        slot = find_current_slot(slots, offset)
        offset = False
        
        if not (slot is None):
            logging.debug("Time slot found!")
            logging.debug(f"start: {slot.start}\nend: {slot.end}")

            some_album_played = False
            #get slot albums
            for dir, tracks, album_metadata in slot.albums:
                if restart:
                    break

                #check if album is blacklisted:
                if not dir in ALBUM_BLACKLIST or has_day_passed(ALBUM_BLACKLIST[dir]):
                    #update blacklist last_played
                    ALBUM_BLACKLIST[dir] = datetime.datetime.now()
                else:
                    continue #skip this album
                
                remaining_seconds = get_remaining_seconds(slot)
                logging.debug(f"remaining seconds: {remaining_seconds}")
                if remaining_seconds <= 900:
                    logging.debug("Ending time slot early...")
                    offset = True
                    break

                #album playback successfull
                some_album_played = True

                logging.debug("Accessing album at directory " + dir)
                #update current image (find using imgdhr)
                update_image_file(dir, album_metadata)

                #loop through tracks (cache album length?)
                album_length = 0
                for file_path, track_metadata in tracks:
                    length = float(track_metadata['length'])
                    album_length += length
                         
                    #update metadata.txt
                    update_metadata_file(track_metadata, ices_process)  
                    logging.debug("Metadata.txt updated!")

                    #decode file into raw pcm (ffmpeg run)
                    logging.debug(f"Converting file {track_metadata['filename']} to pcm:")
                    pcm = to_pcm(file_path)

                    #pipe pcm to ices (terminate after 5 minutes if applicable):
                    logging.debug("Writing pcm to IceS process stdin:")
                    ices_process.stdin.write(pcm)
                    ices_process.stdin.flush()
                        
                    #check if config was edited
                    recent_last_edited = os.path.getmtime(USER_CONFIG_PATH)
                    if last_edited != recent_last_edited:
                        logging.debug("Config edited, updating slots and restarting...")
                        last_edited = recent_last_edited 
                        slots = parse_slots()

                        #look for new slot
                        restart = True
                        offset  = False
                        break

                # Time slot finished
                
                #check if album runtime has surpassed alloted slot time
                if album_length >= remaining_seconds:
                    logging.debug("Album surpassed slot length. Seeking new slot...")
                    offset = False
                    break
                
                #looping...

            #end of slot!
            if not some_album_played:
                logging.debug("No album played. Check that sufficient albums have been supplied. Sleeping for 60 seconds...")
                time.sleep(60)

                #check if config was edited
                recent_last_edited = os.path.getmtime(USER_CONFIG_PATH)
                if last_edited != recent_last_edited:
                    logging.debug("Config edited, updating slots and restarting...")
                    last_edited = recent_last_edited 
                    slots = parse_slots()

        else:
            #sleep for an amount of time, play an intermission, etc... then try again
            logging.debug("No slot available. Check that slots are specified. Sleeping for 60 seconds...")
            time.sleep(60)

            #check if config was edited
            recent_last_edited = os.path.getmtime(USER_CONFIG_PATH)
            if last_edited != recent_last_edited:
                logging.debug("Config edited, updating slots and restarting...")
                last_edited = recent_last_edited 
                slots = parse_slots()

except KeyboardInterrupt:
    ices_process.stdin.close()
    ices_process.wait()
    logging.debug(f"\nIceS closed with exit code: {ices_process.poll()}")

except:
    logging.exception("Unexpected error:")
    ices_process.stdin.close()
    ices_process.wait()
    logging.debug(f"\nIceS closed with exit code: {ices_process.poll()}")
