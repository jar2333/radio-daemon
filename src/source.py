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
from random import shuffle

import logging

logging.basicConfig(level=logging.DEBUG, filename='./log/app.log')

def to_pcm(file_path):
    #hardcoded: sample rate 44100, channels 2. IceS expects these two values (specified in ices.xml)
    cmd = ["ffmpeg", "-i", file_path, "-ar", "44100", "-ac", "2", "-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-"]

    ffmpeg_process = subprocess.run(cmd, capture_output=True)

    return ffmpeg_process.stdout

def update_metadata_file(track_metadata, ices_process):
    #add accessed metadata, sensitive to when this file is written!
    track_metadata['accessed'] = str(datetime.datetime.now(datetime.timezone.utc))

    with open('tmp/metadata.txt', 'w') as f:
        f.write("\n".join([f"{key}={track_metadata[key]}" for key in track_metadata]))
    #send signal to ices process that metadata.txt updated     
    ices_process.send_signal(signal.SIGUSR1)    

def update_image_file(dir, album_metadata):
    image_file = album_metadata['image']
    image_type = album_metadata['image_type']
    shutil.copy(f"{dir}/{image_file}", "tmp/current")

def get_file_metadata(file_path):
    f = mutagen.File(file_path)
    if f is None: #if not audio/failed
        return None
    tags = dict(f.tags) #make it not return a (key, singleton list) pair?
    length = f.info.length

    #add filename to tags:
    filename = file_path.split('/')[-1]
    tags['filename'] = [filename]

    return (tags, length)

def create_track_metadata(file_metadata, album_metadata, slot):
    tags, length = file_metadata

    track_metadata = dict(album_metadata) #copy
    for key in tags:
        if not key in track_metadata:
            track_metadata[key] = tags[key][0]

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
        album_metadata['image_type'] = file_type

        self.albums.append((dir, tracks, album_metadata))

    def is_current(self):
        current = datetime.datetime.now().time()
        return self.start <= current <= self.end

def parse_slots():
    slots = []

    #read config
    tree = ET.parse('user-config.xml')
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
            print(f"parsed album: {dir.split('/')[-1]}")

    return slots

def find_current_slot(slots):
    slot = None
    for s in slots:
        if s.is_current():
            slot = s
            break
    return slot

def exceeds_slot(length, slot):
    current       = datetime.datetime.now()
    end_delta     = datetime.timedelta(hours=slot.end.hour, minutes=slot.end.minute)
    current_delta = datetime.timedelta(hours=current.hour, minutes=current.minute)

    return (end_delta - current_delta).total_seconds() < length

#slots (defined by user-config.xml)
#--albums (directory)
#----songs (files)

#things to update, and when:
# change slot  -> new genre -> update metadata.txt
# change album -> new album title, album artist, album year -> update metadata.txt
# change song  -> new song title, song artist, song year -> update metadata.txt

slots = parse_slots()
last_edited = os.path.getmtime('user-config.xml')

#start ices stream (CONSTANT)
ices_process = subprocess.Popen(['ices', './config/ices.xml'], 
                                stdin=subprocess.PIPE, 
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
print("Initializing IceS...")
time.sleep(3)
print("IceS started.")

try:
    while True:
        restart = False #flag initialize

        print("Finding time slot...")
        #find currently applicable slot
        slot = find_current_slot(slots)
        
        if not (slot is None):
            print("Time slot found!")
            print(f"start: {slot.start}\nend: {slot.end}")

            #get slot albums
            for dir, tracks, album_metadata in slot.albums:
                if restart:
                    break

                print("Accessing album at directory " + dir)
                #update current image (find using imgdhr)
                update_image_file(dir, album_metadata)

                for file_path, track_metadata in tracks:   
                    length = float(track_metadata['length'])

                    #check if song length exceeds slot threshold
                    early_end = exceeds_slot(length, slot)
                         
                    #update metadata.txt
                    update_metadata_file(track_metadata, ices_process)  
                    print("Metadata.txt updated!")

                    #decode file into raw pcm (ffmpeg run)
                    print(f"Converting file {track_metadata['filename']} to pcm:")
                    pcm = to_pcm(file_path)

                    #pipe pcm to ices (terminate after 5 minutes if applicable):
                    print("Writing pcm to IceS process stdin:")
                    ices_process.stdin.write(pcm)
                    ices_process.stdin.flush()
                        
                    if early_end:
                        #look for new slot
                        restart = True
                        break
                    else:
                        #check if config was edited
                        recent_last_edited = os.path.getmtime('user-config.xml')
                        if last_edited != recent_last_edited:
                            # print("Config edited, updating slots and restarting...")
                            last_edited = recent_last_edited 
                            slots = parse_slots()

                            #look for new slot
                            restart = True
                            break

            # Time slot finished, looping
        else:
            #sleep for an amount of time, play an intermission, etc... then try again
            # print("No slot available. Sleeping for 60 seconds...")
            time.sleep(60)

            #check if config was edited
            recent_last_edited = os.path.getmtime('user-config.xml')
            if last_edited != recent_last_edited:
                # print("Config edited, updating slots and restarting...")
                last_edited = recent_last_edited 
                slots = parse_slots()

except KeyboardInterrupt:
    ices_process.stdin.close()
    ices_process.wait()
    print(f"\nIceS closed with exit code: {ices_process.poll()}")

except:
    logging.exception("Unexpected error:")
    ices_process.stdin.close()
    ices_process.wait()
    print(f"\nIceS closed with exit code: {ices_process.poll()}")
