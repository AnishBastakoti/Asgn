from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
<<<<<<< HEAD
    default_limits=["20/minute"]
=======
    default_limits=["60/minute"]
>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
)