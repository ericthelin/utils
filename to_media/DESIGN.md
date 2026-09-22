# to_media design

`to_media` reshapes files (audio, video, images, and later other kinds) from one
format to another. A single command converts inline; the same command can hand
a large batch to a farm of machines that share a job server.

This document records the decisions made while designing it. It is the
reference for the milestones below.

## Contract

| You type | What happens |
| --- | --- |
| `to_mp3 *.flac` | Converts inline in your terminal. No server, no workers. |
| `to_mp3 *.flac --queue` | Submits the files to the server and **returns immediately**, printing the batch name. |
| `to_mp3 *.flac --queue --follow` | Submits, then follows live progress until the batch finishes. Ctrl-C stops following; the jobs keep running. |
| `to_media mp3 *.flac` | Same as `to_mp3`. `to_<format>` commands are aliases of `to_media <format>`. |
| `to_media server` | Starts (or configures, or reports on) the job server. |
| `to_media worker [JOIN]` | Runs a worker for the remembered (or given) server. |
| `to_media jobs`, `to_media status [BATCH] [--watch]` | List queued jobs and report progress. |
| `to_media cancel`, `to_media retry --failed` | Manage jobs. |

Everyday commands need no flags once a server is configured. `--queue` is the
flag rather than `--jobs`, because `-j N` conventionally means "run N in
parallel".

Originals are **kept** by default. `--replace` deletes them, and on the server
side only after the result is verified and in place.

## Structure

```text
to_media/
├── to_media.py            entry point; dispatches on the command name
├── to_medialib/           the implementation (standard library only)
│   ├── config.py         config paths and file
│   ├── jobs.py           the Job record (JSON-serialisable, queue-ready)
│   ├── runner.py         inline runner: skip/dry-run/atomic output/replace
│   ├── media.py          external-program helpers
│   ├── cli.py            argument parsing and dispatch
│   └── recipes/          one module per output format family
└── tests/
```

The tool name lives in one place (`to_medialib/config.py`, `TOOL_NAME`) so that
the config directory and messages follow it.

### Progress

`Recipe.run(job, tmp_output, progress)` takes an optional callback that receives
the fraction complete (0.0 to 1.0). The ffmpeg-based recipes feed it from
ffmpeg's own `-progress` output and the input's duration, and the inline runner
turns it into a live bar with an estimate. A worker will pass a callback that
reports the same fraction to the server, so inline and queued runs share one code
path.

### Metadata

The rule: nothing is lost silently. Every recipe either carries a piece of
metadata across or returns a note saying it was left out and why. The rule came
from measuring: files carrying rich tags, cover art, chapters, GPS and camera data
were converted and compared field by field (with exiftool, MediaInfo and ffprobe)
before deciding what each recipe had to do, and the tests keep real files of that
kind and check the results. Two facts drove the design: MP4 cannot hold a cover
picture and QuickTime-style custom tags together, and copying an MKV cover through
ffmpeg leaves a bare video track unless it is extracted and re-attached. Every
output also keeps its source's modification time.

### Subtitles (h264)

MP4 holds only text subtitles, so the plan for each file depends on what is in it:
text tracks become `mov_text` and are kept; image tracks (PGS, VobSub, DVB) cannot
go in an MP4 and produce a visible `note:` rather than vanishing; the MKV
container keeps everything; `--burn-subtitles` renders one track into the
picture (libass for text, an overlay for images). Recipes may return notes from
`run`, which the runner prints even without `-v`, and a failed subtitle
conversion retries the file without subtitles and says so, so one odd track does
not fail a file in a large batch.

### Recipes

A recipe knows how to turn inputs into one output format: its input extensions,
the programs it needs, its options, and the command to run. Recipes are either
**one-to-one** (each file becomes a file: mp3, jpg, png, webp) or
**many-to-one** (a folder becomes one file: m4b audiobooks). Backends are
detected, not hard-coded: ffmpeg for audio and video, ImageMagick (`magick`,
falling back to `convert` on Unix) for images. Later kinds (documents, ebooks)
add recipes, not core code.

A **job** is plain data: recipe name, inputs, output, options. It never contains
a shell command. Workers rebuild the command from the recipe, so a job cannot
carry arbitrary code.

## Server, worker and client (milestones 3 and 4)

```text
 to_mp3 --queue ─►┌───────────────────┐◄── to_media jobs / status / web page
                  │  server           │
                  │  SQLite (local    │
                  │  disk, not NFS)   │
                  └───▲───────▲───────┘
           claim job  │       │ heartbeat + progress %
             ┌────────┴─┐ ┌───┴──────┐
             │ worker A │ │ worker B │ ...
             └──────────┘ └──────────┘
```

* The server stores jobs and their state (queued, running, done, failed),
  retries, priorities, per-job logs and progress. It has a JSON API over HTTP,
  a CLI (`jobs`, `status`) and a simple status web page. Standard library only.
* Workers claim jobs with a **lease and heartbeat**. A worker that dies or goes
  quiet returns its job to the queue after the lease expires. Progress comes
  from ffmpeg's or ImageMagick's own output.
* Each worker reports its capabilities (programs found, GPU encoders, CPU
  budget) and only receives jobs it can run.
* Small jobs are **claimed in chunks**, because a HEIC conversion takes a second
  and a server round trip per image would cost more than the work.
* A server restart keeps the queue. A worker that cannot reach the server
  retries with backoff and never exits by itself.
* Duplicate work is harmless: output is written to a temporary file and renamed
  atomically, and a result from a worker whose lease was given away is rejected
  and its temporary file deleted.

### Data transfer

Each worker has a mode: `shared` (files reached over NFS or SMB, read and written
in place), `transfer` (files moved over the server connection), or `auto`
(default): the worker probes whether it can see the job's source and falls back
to transfer.

Transfer sequence: claim, check free scratch space, download the source
(streamed, resumable, SHA-256 checked) to scratch, convert locally, upload the
result (streamed), the server verifies the checksum, writes a temporary file in
the destination folder, renames it atomically and, only if `--replace` was
requested, then deletes the original.

Only the server needs access to sources and destinations. Workers never choose
paths: the server decides the destination from the job, so a worker cannot write
anywhere a job does not name. The server limits concurrent transfers because it
becomes the hub; `auto` prefers shared storage when it is reachable.

Paths in a job are relative to a named **share**, so machines that mount the same
storage at different places (`/mnt/media`, `Z:\`) still agree. A client that is
not on the shared storage cannot name files the server can read; uploading
sources from such a client is a possible later option.

Audible activation keys (a later recipe input) stay in the worker's own config
and never pass through the server.

## `to_media server`

One command that does the right thing for the current state:

| State | Behaviour |
| --- | --- |
| First run | Picks a free port, generates a token, asks the setup questions, writes the config, starts serving in the background and prints the **join string**. |
| Configured, not running | Starts serving and prints the join info. |
| Already running here | Does not start a second one; shows the join info and a status summary. |

* **Background by default.** `--foreground` keeps it attached. `--stop` and
  `--status` manage a background server. A later `--install-service` would write
  the systemd, launchd or Task Scheduler entry.
* **Logging.** `--log system` (default: syslog or journald on Linux, syslog on
  macOS, a file under `%ProgramData%` on Windows), `--log console` (foreground
  only) or `--log /path/to/file` (rotating).
* **`--setup`** forces the setup questions again, on both server and worker,
  with current values as the defaults.
* **Address.** Setup asks how workers should find the server: hostname, IP,
  both (hostname first, IP as fallback), or a value you give. Flag:
  `--advertise hostname|ip|both|VALUE`. Usable IPs are listed with loopback,
  Docker bridges and VPNs filtered out. Workers try each address in order, keep
  the one that worked and warn when they are on the fallback.
* `--new-token` rotates the token and invalidates old join strings.
  `--join-info` prints only the join string.

## `to_media worker [JOIN]`

| State | Behaviour |
| --- | --- |
| A join string is given | Tests it, saves it as the remembered server (replacing any earlier one and saying so) and starts working. |
| No argument, server remembered | Connects to it and works. |
| No argument, nothing remembered | Explains how to get a join string. |
| Server unreachable | Keeps retrying with backoff and says why. |
| Server moved or token rotated | Says a new join string is needed. |

The join string is a readable URL, `tomedia://TOKEN@host[,host2]:port`, with a
short server id so a worker can tell "server down" from "a different server is
at this address". It contains the token, so it is a secret.

## `--queue` when there is no usable server

Interactive runs get a menu. Non-interactive runs get an error carrying the same
guidance. It never falls back to converting inline.

* **No server configured:** start one on this machine (runs setup), paste a join
  string, or cancel.
* **Configured but unreachable:** retry, start it here (if this machine is the
  configured host), start a new server here (reconfigures), paste a new join
  string, or cancel; the reason (timeout, refused, bad token) is stated.

A machine that only submits jobs needs no third command: the first `--queue`
with no server known prompts for the join string and saves it, or `--server JOIN`
can be given.

## Security

* Jobs are structured data, never shell commands, and workers only run recipes
  they know.
* The server needs a shared token and should bind to the LAN only.
* **TLS:** the server uses `openssl` if it is installed to create a certificate,
  and the join string carries the certificate fingerprint so workers pin it. If
  `openssl` is not available the server prints an "unencrypted" warning at start
  and each worker prints one when it connects.
* The database lives on the server's local disk, never on NFS.
* Config files holding tokens are created mode 600.

## Milestones

1. **Shared core and the first recipes, inline only** (done): the Job record,
   runner, `to_media formats`, and the mp3, jpg, png, webp and m4b recipes, with
   tests on generated media.
2. **The h264 recipe (done), then parity with the old converters** so the `to_*`
   commands can be pointed at `to_media`. Audible input and re-encoding
   existing MP3s are done for `to_mp3`. Still to do: FLAC albums split by
   `.cue` and per-chapter splitting, both of which need one source to become
   several outputs; today a recipe's `plan()` can only turn several sources
   into one output (`many_to_one`, as `m4b` does), not the other way round.
   `to_m4b` and `to_h264` are functionally covered (with the differences
   listed in the README).
3. **Server, worker and client CLI, plus the status page and TLS** (done): the
   SQLite queue with leases and retries, the HTTP job server and status page,
   the worker (with heartbeat-driven cancellation), `to_media server`/`worker`/
   `jobs`/`status`/`cancel`/`retry`/`--queue`/`--follow`, including the prompts
   when no server is configured or reachable, background start/stop by
   default, the `tomedia://` join string, and the self-signed certificate with
   fingerprint pinning described above. Shared-path mode only: a worker needs
   the same paths the server sees.
4. Data transfer mode (so a worker needs no shared storage), chunked claims
   for small jobs.
5. Retire the old Perl and PHP converters and Gearman.

## Open items

* How a client that is not on the shared storage submits files.
* Windows logging beyond a plain file (the standard library cannot write the
  Event Log).
* Whether to add a service installer (`--install-service`).
