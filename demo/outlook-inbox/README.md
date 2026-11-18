# Demo Outlook inbox

Six synthetic, header-only `.eml` files used by the Outlook Brief demo on
2026-11-18. They exercise a real thread (`Re:` replies), one high-importance
message, one no-reply sender and recency ranking.

Point **Settings > Mail source > Mail folder** at this directory and turn the
mail digest on. The watcher reads only From, To, Cc, Subject, Date, Message-ID,
In-Reply-To and Importance. Bodies are discarded at parse time.

For a real mailbox, `tools/export-outlook.ps1` writes the same shape from a
configured Outlook profile. It uses Windows PowerShell 5.1 and Outlook COM:

```powershell
powershell.exe -ExecutionPolicy Bypass -File tools\export-outlook.ps1 -OutDir C:\mail-exports -Days 14
```

The first file is the top message in the demo: Priya Raman asks for Q4 numbers
by EOD and marks the message high importance. The card ranks it first and builds
three reply starters from the subject line, never from the body.
