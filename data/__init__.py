"""Data module - Suppress SmartAPI debug logs"""
import logging
logging.getLogger('smartConnect').setLevel(logging.ERROR)
logging.getLogger('SmartApi').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
