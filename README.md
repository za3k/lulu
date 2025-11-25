[Hack-a-Day](https://za3k.com/hackaday) is my self-imposed challenge to do one project a day, for all of November.

Written by [Claude](https://claude.ai) and [za3k](https://za3k.com)

This is a command-line program which takes a PDF, and publishes it, sending it to your house, and pays for it with your credit card.

Copy `sample-env` to `.env` and edit it to add personal info. You will need to make a [lulu.com](https://www.lulu.com) account to use the program.

Usage:

    python lulu_automation.py /path/to/your/book.pdf "Title" "Subtitle" "Author"

Lulu supports only specific sizes for pages -- most standard page sizes are OK.

The cover is auto-generated for you, using the title and author provided.
