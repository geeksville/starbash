* must be optin/optional

To add Google Analytics to a Jekyll site using Markdown, you do not add the tracking code directly inside your .md files. Instead, you place the code once into a layout template (an HTML file), and Jekyll will automatically apply it to all your Markdown pages.
Here is the fastest way to set it up:
## Step 1: Add Your Measurement ID to _config.yml
Open your root _config.yml file and add your Google Analytics tracking ID at the bottom. This keeps your ID organized and easy to change later.

google_analytics: G-XXXXXXXXXX

(Replace G-XXXXXXXXXX with your actual Google Analytics 4 Measurement ID).
## Step 2: Create the Analytics HTML Include

   1. Look for a folder in your project named _includes. If it does not exist, create it.
   2. Inside _includes, create a new file named google-analytics.html.
   3. Paste the following official Google Analytics tracking code into that file:

{% if site.google_analytics and jekyll.environment == "production" %}<!-- Google tag (gtag.js) -->
<script async src="https://googletagmanager.com{{ site.google_analytics }}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', '{{ site.google_analytics }}');
</script>
{% endif %}

Note: The if statement ensures that data is only tracked when the site is live on GitHub Pages (production), preventing your local development testing from messing up your analytics data.
## Step 3: Insert the Code Into Your Main Layout
You need to inject this tracking script into the <head> section of your website.

   1. Open your _layouts folder.
   2. Open your default or main layout file (usually named default.html or head.html).
   3. Paste the liquid include tag just before the closing </head> tag:

  {% include google-analytics.html %}
</head>

## Step 4: Deploy and Verify
Commit your changes and push them to GitHub.
Because of the environment check code used in Step 2, you must build your site with the production environment flag if you want to test it locally:

JEKYLL_ENV=production bundle exec jekyll serve

To see if it works on your live GitHub Pages site, open your webpage in a browser, then check the Realtime report inside your Google Analytics dashboard to see your active visit.
If you hit any snags, let me know:

* What Jekyll theme are you using? (Some themes have this built into a specific file name).
* Do you see any errors when you build your site?
* Do you want to track custom events, like when someone clicks a specific link in your Markdown?


