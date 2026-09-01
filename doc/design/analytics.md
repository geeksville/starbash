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

