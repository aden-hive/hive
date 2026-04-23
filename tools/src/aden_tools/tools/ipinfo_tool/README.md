# IPInfo Tool

IP geolocation and network intelligence for Hive agents using ipinfo.io.

## Authentication
Requires a free IPInfo token. Sign up at https://ipinfo.io/signup.
Set `IPINFO_TOKEN` environment variable.

## Tools

### ipinfo_get_ip_details
Get location and network data for any IP address.
- `ip` (str): IP address e.g. 8.8.8.8

### ipinfo_get_my_ip
Get location and network data for the current machine's IP.

## Returns
ip, city, region, country, org, timezone, loc (lat/lon)

## License
Data provided under CC BY-SA 4.0 (attribution required).
Free tier: 50,000 requests/month.
