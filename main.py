import zeep
import requests
from onvif.client import ONVIFCamera
from onvif.exceptions import ONVIFError
import time
from os import getenv, getcwd, path
import threading

# NVR Configuration
IP = getenv('IP')
PORT = getenv('PORT')
USER = getenv('USER')
PASS = getenv('PASS')
WSDL_DIR = path.join(getcwd(), 'wsdl')

def get_device_service_capabilities(mycam):
    try:
        device_service = mycam.create_devicemgmt_service()  # Use Device Management service
        capabilities = device_service.GetServiceCapabilities()
        return capabilities
    except Exception as e:
        print(f"Error retrieving device service capabilities: {e}")
        return None

def get_event_service_capabilities(mycam):
    event_service = mycam.create_events_service()
    capabilities = event_service.GetServiceCapabilities()
    return capabilities

def get_rtsp_urls(mycam, profiles):
    rtsp_urls = {}
    media_service = mycam.create_media_service()
    for profile in profiles:
        configuration = media_service.GetStreamUri({
            "StreamSetup": {
                "Stream": "RTP-Unicast",
                "Transport": {"Protocol": "RTSP"}
            },
            "ProfileToken": profile.token
        })
        rtsp_urls[profile.token] = configuration.Uri
    return rtsp_urls

def get_camera_statuses(profiles, video_sources):
    active_cameras = set()
    inactive_cameras = set()
    all_cameras = {vs.token for vs in video_sources if vs.token}
    for profile in profiles:
        profile_video_sources = profile.VideoSourceConfiguration.SourceToken
        if profile_video_sources in all_cameras:
            active_cameras.add(profile_video_sources)
            all_cameras.remove(profile_video_sources)
    inactive_cameras = all_cameras
    return active_cameras, inactive_cameras

def report_camera_changes(status_type, current_cameras, previous_cameras):
    added_cameras = current_cameras - previous_cameras
    removed_cameras = previous_cameras - current_cameras
    if added_cameras:
        print(f"Cameras became {status_type}: {', '.join(added_cameras)}")
    if removed_cameras:
        print(f"Cameras became not {status_type}: {', '.join(removed_cameras)}")

def poll_camera_statuses(mycam, initial_active_cameras, initial_inactive_cameras, should_stop):
    while not should_stop.is_set():
        try:
            media = mycam.create_media_service()
            profiles = media.GetProfiles()
            video_sources = media.GetVideoSources()

            current_active, current_inactive = get_camera_statuses(profiles, video_sources)

            if current_active != initial_active_cameras or current_inactive != initial_inactive_cameras:
                report_camera_changes("Active", current_active, initial_active_cameras)
                report_camera_changes("Inactive", current_inactive, initial_inactive_cameras)
                initial_active_cameras, initial_inactive_cameras = current_active.copy(), current_inactive.copy()

        except (ONVIFError, zeep.exceptions.Fault, ConnectionError) as e:
            print(f"Error communicating with camera: {e}")
            time.sleep(2)  # Retry after 2 seconds
            continue

        time.sleep(1)  # Sleep for 1 second

if __name__ == "__main__":
    try:
        # Connect to ONVIF Camera
        mycam = ONVIFCamera(IP, PORT, USER, PASS, WSDL_DIR)
        print("Connected to DVR successfully!")

        # Get Device Service Capabilities
        device_capabilities = get_device_service_capabilities(mycam)
        if device_capabilities:
            print("\n--- Device Service Capabilities ---")
            print(device_capabilities)

        # Get Event Service Capabilities
        event_capabilities = get_event_service_capabilities(mycam)
        print("\n--- Event Service Capabilities ---")
        print(event_capabilities)

        # Get Device and System Information (Optional)
        devicemgmt = mycam.create_devicemgmt_service()
        device_info = devicemgmt.GetDeviceInformation()
        system_date_and_time = devicemgmt.GetSystemDateAndTime()

        print("\n--- Device Information ---")
        print(f"- Manufacturer: {device_info.Manufacturer}")
        print(f"- Model: {device_info.Model}")
        print(f"- Firmware Version: {device_info.FirmwareVersion}")
        print(f"- Serial Number: {device_info.SerialNumber}")

        print("\n--- System Date and Time ---")
        if system_date_and_time and system_date_and_time.UTCDateTime:
            print(f"- Current Time: {system_date_and_time.UTCDateTime.Time}")
            print(f"- Current Date: {system_date_and_time.UTCDateTime.Date}")

        # Get Initial Camera Statuses
        media_service = mycam.create_media_service()
        profiles = media_service.GetProfiles()
        video_sources = media_service.GetVideoSources()
        initial_active_cameras, initial_inactive_cameras = get_camera_statuses(profiles, video_sources)

        print("\n--- Initial Camera Status ---")
        report_camera_changes("Active", initial_active_cameras, set())
        report_camera_changes("Inactive", initial_inactive_cameras, set())

        # Start Polling in a Background Thread with stop flag
        stop_polling = threading.Event()
        polling_thread = threading.Thread(target=poll_camera_statuses,
                                          args=(mycam, initial_active_cameras.copy(), initial_inactive_cameras.copy(),
                                                stop_polling))
        polling_thread.daemon = True
        polling_thread.start()

        # Enhanced RTSP URL Retrieval and Error Handling
        rtsp_urls = get_rtsp_urls(mycam, profiles)
        print("\n--- RTSP URLs ---")
        for profile in profiles:
            rtsp_url = rtsp_urls.get(profile.token, "N/A")
            if rtsp_url == "N/A":
                print(f"RTSP URL not available for profile: {profile.Name} (Token: {profile.token})")
            else:
                print(f"- {profile.Name} (Token: {profile.token}): {rtsp_url}")

        while True:
            time.sleep(60)  # Main thread keeps running

    except (ONVIFError, zeep.exceptions.Fault, ConnectionError) as e:
        print(f"Fatal ONVIF Error: {e}")
        stop_polling.set()  # Stop the polling thread in case of fatal errors
