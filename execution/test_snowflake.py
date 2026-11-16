# execution/test_snowflake.py
import socket
import urllib.request

def test_dns(host):
    print(f"Resolving {host}...")
    try:
        ip = socket.gethostbyname(host)
        print(f"Success: {ip}")
    except Exception as e:
        print(f"Failed to resolve {host}: {e}")

def test_http(url):
    print(f"Connecting to {url}...")
    try:
        response = urllib.request.urlopen(url, timeout=5)
        print(f"HTTP Status: {response.status}")
    except Exception as e:
        print(f"HTTP connection failed: {e}")

test_dns("google.com")
test_dns("fs03183.ap-south-1.aws.snowflakecomputing.com")
test_http("https://www.google.com")
