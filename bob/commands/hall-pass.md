---
description: Publish the Hall Pass for this session as a shareable one-page summary
---
Call the hall-monitor hall_pass tool. It writes the Hall Pass to .hallmonitor/hall-pass.html and returns the file's full path and a short summary. Give me the summary and the full path, so I can open the file in a browser; that is all this command needs. Don't read the file with a shell command, don't paste its HTML, and don't write an html_artifact tag. Only if your tools include create_html_artifact (Bob IDE 2.2.1 has none): read the file with your read_file tool, publish it with create_html_artifact, and give me the artifact too.
