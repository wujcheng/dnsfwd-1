import os

import pymemcache.client
from werkzeug.wrappers import Request

from utils.dns import lookup_cname, lookup_txts
from utils.text import cut_prefix, cut_suffix


cache = pymemcache.client.Client((os.getenv('MEMCACHE_HOST', 'localhost'), os.getenv('MEMCACHE_PORT', 11211)))
cache.get('test') # make sure we're connected


def lookup_fwd(domain, rdepth = 1):
	"""Look up the forwarding address for a domain."""
	
	cached = cache.get(domain)
	if cached is not None:
		return cached.decode('ascii')
	
	cname, ttl = lookup_cname(domain)
	
	if cname is None:
		txts, ttl = lookup_txts(domain)
		for txt in txts:
			# DNSFwd TXT format
			dnsfwd_txt = cut_prefix(txt.lower(), 'dnsfwd ')
			if dnsfwd_txt:
				cname = dnsfwd_txt + '.dnsfwd.com'
				break
			
			# DNSimple ALIAS format
			dnsimple_alias = cut_prefix(txt.lower(), 'alias for ')
			if dnsimple_alias:
				cname = dnsimple_alias
				break
	
	if cname is None:
		return None
	
	fwd_to = cut_suffix(cname, '.dnsfwd.com')
	if not fwd_to:
		# It could be an intermediary CNAME that points to our CNAME, which should work but not get stuck in a loop.
		
		rdepth += 1
		if rdepth > 3:
			return None
		
		return lookup_fwd(cname, rdepth)
	
	cache.set(domain, fwd_to.encode('ascii'), ttl)
	
	return fwd_to


def app(environ, start_response):
	request = Request(environ)
	
	domain, _, port = request.host.partition(':')
	
	fwd_to = lookup_fwd(domain)
	
	if fwd_to == 'unwww' and domain.startswith('www.'):
		fwd_to = domain[4:]
	
	status = '301 Moved Permanently'
	if fwd_to is not None:
		location = 'http://' + fwd_to + request.path
	else:
		location = 'http://dnsfwd.com/#improperly_configured'
	
	response_headers = [
		('Content-Length', '0'),
		('Location', location),
	]
	start_response(status, response_headers)
	return ()


if __name__ == '__main__':
	from werkzeug.serving import run_simple
	
	run_simple('localhost', 8000, app)
