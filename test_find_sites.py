from find_sites import (EMAIL_PATTERN, LINK_PATTERN, QUOTED_PATTERN,
                        find_websites_in_text, load_domain_endings)

endings = load_domain_endings()

# Links: any scheme, no scheme ("//"), any real ending like .xyz.
# "localhost" and "main.js" are skipped because "localhost" and "js" are not real endings.
text = 'a="https://CDN.Example.com/app.js" b="wss://live.site.xyz" c="//img.site.in/x.png" d="http://localhost:3000" e="https://main.js"'
found = find_websites_in_text(text, LINK_PATTERN, endings)
assert found == ["cdn.example.com", "live.site.xyz", "img.site.in"], found

# Emails
text = "contact support@help.site.xyz or v1.2@9.x"
found = find_websites_in_text(text, EMAIL_PATTERN, endings)
assert found == ["help.site.xyz"], found

# Quoted names: only when the quote holds just the name (optionally with a path or port)
text = 'fetch("api.site.xyz/v1") x="cdn.site.xyz" y=e.style z="main.js" w="api.site.xyz is down"'
found = find_websites_in_text(text, QUOTED_PATTERN, endings)
assert found == ["api.site.xyz", "cdn.site.xyz"], found

print("ok")
