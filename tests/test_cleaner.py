"""Unit tests for agent.cleaner module."""

from agent.cleaner import (
    clean_html,
    post_process_markdown,
    count_tokens,
    truncate_tokens,
    build_domain_context,
)


def test_post_process_markdown():
    text = "Contact us at [email](mailto:contact@postman.com) or mailto:support@postman.com\n\n\n\nNext line."
    cleaned = post_process_markdown(text)
    assert "contact@postman.com" in cleaned
    assert "support@postman.com" in cleaned
    assert "mailto:" not in cleaned
    assert "\n\n\n" not in cleaned


def test_clean_html_strips_scripts_and_styles():
    html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Postman API Platform</title>
        <style>body { color: red; }</style>
        <script>console.log("analytics tracking code");</script>
      </head>
      <body>
        <nav><a href="/home">Home</a><a href="/login">Login</a></nav>
        <main>
          <h1>Postman API Platform</h1>
          <p>Postman is an API platform for building and using APIs. Over 30 million developers use Postman.</p>
          <h2>Leadership</h2>
          <p>Abhinav Asthana is the CEO and Co-Founder of Postman.</p>
        </main>
        <footer><p>Copyright 2026 Postman Inc. All rights reserved.</p></footer>
      </body>
    </html>
    """
    cleaned = clean_html(html, url="https://postman.com")
    assert "Postman API Platform" in cleaned
    assert "Abhinav Asthana" in cleaned
    assert "console.log" not in cleaned
    assert "color: red" not in cleaned


def test_token_counting_and_truncation():
    text = "Postman is an API platform used by over 30 million developers."
    tokens = count_tokens(text)
    assert tokens > 0

    truncated = truncate_tokens(text, max_tokens=5)
    assert count_tokens(truncated) <= 15  # Includes suffix
    assert "truncated" in truncated


def test_build_domain_context():
    homepage = """
    <html>
      <body>
        <h1>Postman Home</h1>
        <p>The leading platform for API development and collaboration.</p>
      </body>
    </html>
    """
    about_page = """
    <html>
      <body>
        <h1>About Postman</h1>
        <p>Founded in 2014 by Abhinav Asthana, Ankit Sobti, and Abhijit Kane.</p>
      </body>
    </html>
    """
    pages = [
        ("https://postman.com/about", about_page),
        ("https://postman.com", homepage),
    ]

    context, stats = build_domain_context(pages, max_tokens=2000)
    assert "## Source: https://postman.com" in context
    assert "## Source: https://postman.com/about" in context
    assert "Abhinav Asthana" in context
    assert stats["raw_chars_total"] > stats["clean_chars_total"]
    assert stats["compression_ratio_pct"] > 0
    assert stats["token_count"] > 0
    assert len(stats["pages_included"]) == 2
