# Publish to GitHub using free resources

## Published deployment

- Source: [adhisha-sahoo/AIproject](https://github.com/adhisha-sahoo/AIproject).
- Demo: [CloudDesk on GitHub Pages](https://adhisha-sahoo.github.io/AIproject/#overview).
- [Successful deployment run #2](https://github.com/adhisha-sahoo/AIproject/actions/runs/38459573350).

The source was published through GitHub's Git tree/commit/ref APIs. Pages uses the repository's GitHub Actions workflow and deploys after verification succeeds. The deployed browser was checked for request creation, plan approval, cleanup, and cited runbook retrieval. These interactions are explicitly labeled simulations.

## What will be hosted

A **public repository** can host the browser demonstration on GitHub Pages with GitHub Free. Pages serves static HTML/CSS/JavaScript; Python, Jenkins, and the AWS emulator run on your computer. The public site does not include credentials or connect to your local infrastructure.

## API/CLI publication

Install the free [GitHub CLI](https://cli.github.com/) and Git, then authenticate to your own account:

```sh
gh auth login
```

For public repositories with GitHub Actions workflows, your authentication must permit repository creation and workflow writes. The CLI handles authentication; do not paste a personal access token into source files or the chat.

From the project root:

```sh
python -m pip install -e '.[dev]'
python scripts/publish_github.py --name clouddesk --visibility public
```

The publisher verifies the project, resolves the actual authenticated GitHub account through its API, creates a new repository, commits only allowlisted project files, pushes `main`, enables Pages through the API, and prints the repository and expected demo URLs. It refuses to overwrite an existing remote or reuse an existing repository.

Creating a public repository makes the source publicly readable. Choose this for the free Pages demonstration. The source archive contains no resume upload, phone number, email address, or generated `.env` credentials.

After pushing, open the repository's **Actions** tab. `Verify CloudDesk` runs the API/model/JavaScript checks and the Terraform integration test on Linux. A successful `main` push triggers `Publish free browser demo`. The demo's link appears under **Settings → Pages** after deployment.

The publisher does not label the expected Pages URL as live until GitHub has successfully deployed it. If repository/Pages administration is not permitted by your account token, it reports that failure rather than claiming deployment succeeded.

## Manual alternative

If you prefer your own Git workflow:

1. Create a new, empty, public repository named `clouddesk` in your own account.
2. Upload/push the project's source, including `.github/workflows/`; exclude `.env`, `.data`, `.venv`, caches, and Terraform state.
3. In **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source.
4. Confirm `Verify CloudDesk` succeeds and the Pages workflow deploys.

GitHub's deployment process requires repository permissions. Installing a connector alone does not prove that a currently running session has callable publishing APIs; account access and publication must be verified.

## Entire backend hosting

The free, fully working backend deployment is local: `docker compose up --build`, or the Python quickstart in README.md. This project deliberately avoids free cloud trials, payment cards, or assumptions about remaining AWS credits. It does not claim to run the Python service on GitHub Pages.
