# CI

## `gitlabci`

`bt gitlabici` prints configuration for Gitlab Continuous Integration to the terminal.
This can be piped into the `.gitlab-ci.yml` file in the root of the repository.
When there are multiple contests, just append the `bt gitlabci` of each of them, but deduplicate the top level `image:` and `default:` keys.

Use the `--latest-bt` flag to pull the latest version of BAPCtools before each run.
By default, the version in the docker image is used.

Example output:

```sh
~nwerc2020 % bt gitlabci
image: bapctools

default:
  before_script:
    - git -C /cache/BAPCtools pull || git clone https://github.com/RagnarGrootKoerkamp/BAPCtools.git /cache/BAPCtools
    - ln -s /cache/BAPCtools/bin/tools.py bt

contest_pdf_nwerc2020:
  script:
      - ./bt pdf --cp --no-bar --contest nwerc2020
      - ./bt solutions --cp --no-bar --contest nwerc2020
  only:
    changes:
      - nwerc2020/testproblem/statement/**/*

  artifacts:
    expire_in: 1 week
    paths:
      - nwerc2020/solution*.pdf
      - nwerc2020/contest*.pdf

verify_testproblem:
  script:
      - ./bt all --cp --no-bar --problem nwerc2020/testproblem
  only:
    changes:
      - nwerc2020/testproblem/**/*
  artifacts:
    expire_in: 1 week
    paths:
      - nwerc2020/testproblem/problem*.pdf
```

The default behaviour is:

- Use the `bapctools` Docker image.
This has to be installed manually from the [Dockerfile](../installation/#docker) found in the root of the repository.
- Before each stage, pull `BAPCtools` to the `/cache` partition.
This makes sure to always use the latest version of BAPCtools.
- For contests: build the problem and solutions pdf and cache these artefacts 1 week.
- For problems: run `bt all` on the problem and keep the problem pdf for 1 week.

We use the following configuration for the gitlab runners:

```toml
[[runners]]
  name = "BAPC group runner"
  url = "<redacted>"
  token = "<redacted>"
  executor = "docker"
  [runners.custom_build_dir]
  [runners.docker]
    tls_verify = false
    image = "bapctools"
    privileged = false
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = ["/cache"]
    shm_size = 0
    pull_policy = "never"
    memory = "2g"
    memory_swap = "2g"
  [runners.cache]
    [runners.cache.s3]
    [runners.cache.gcs]
  [runners.docker.tmpfs]
    "/tmp" = "rw,exec"
```

## `forgejo_actions`

`bt forgejo_actions` writes Forgejo Actions workflows for the current contest to the `.forgejo` directory in the root of the git repository.
When there are multiple contests, run `bt forgejo_actions` once for each contest (either in the contest directory, or by passing `--contest <contest>`).

Use the `--latest-bt` flag to pull the latest version of BAPCtools before each run.
By default, the version in the docker image is used.

The generated workflows are similar to those for `bt gitlabci` described above.

For smooth operation, use the following in the forgejo runner `config.yaml` to increase the memory limit of the container and mount `/tmp` to memory.
```
container:
  options: --memory=4g --memory-swap=4g --tmpfs /tmp:exec
```
and use the following label in `.runner`:
```json
{
  "labels": [
    "bapctools-docker:docker://ragnargrootkoerkamp/bapctools"
  ]
}
```

## `github_actions`

`bt github_actions` writes Github Actions workflows for the current contest to the `.github` directory in the root of the git repository.
When there are multiple contests, run `bt github_actions` once for each contest (either in the contest directory, or by passing `--contest <contest>`).

The generated workflows are similar to those for `bt gitlabci` described above.
