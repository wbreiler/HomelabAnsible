# Homelab Ansible Playbook

This repository provides a comprehensive Ansible playbook designed to automate the setup and configuration of a personal homelab server. It handles everything from initial package installation and system updates to deploying containerized applications with Docker Compose.

## Overview

The primary goal of this project is to create a repeatable and consistent environment for a homelab. By defining the server's desired state in code, it becomes easy to provision new machines or recover an existing one. This playbook is structured using Ansible Roles to ensure modularity and reusability.

The playbook performs the following high-level actions:
1.  **System Preparation**: Updates all system packages and installs essential tools (`curl`, `git`, `vim`, etc.).
2.  **Docker Environment**: Installs and configures Docker Engine and Docker Compose.
3.  **Tailscale VPN**: Installs and enables the Tailscale agent for secure remote access.
4.  **Application Deployment**: Deploys a stack of applications defined in Docker Compose files.

## Prerequisites

Before you begin, ensure you have the following:
*   **Ansible**: Installed on the machine you will run the playbook from (the control node). The `community.docker` collection is also required and can be installed with the following command:
    ```bash
    ansible-galaxy collection install community.docker
    ```
*   **SSH Access**: Key-based SSH access configured from your control node to the target homelab server(s).
*   **Target Host**: A fresh installation of a Debian-based (like Raspberry Pi OS, Debian, Ubuntu) or Fedora-based (like Fedora, CentOS) Linux distribution on your homelab server.

## Getting Started

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/your-username/HomelabAnsible.git
    cd HomelabAnsible
    ```

2.  **Configure the Inventory**
    Open the `inventory.ini` file and replace the placeholder IP address with the actual IP address or hostname of your homelab server.
    ```ini
    [homelab]
    pi1 ansible_host=192.168.1.100

    [all:vars]
    ansible_user=pi
    ```
    Update `ansible_user` to the remote user you will be connecting as.

3.  **Add Docker Compose Files**
    This playbook expects a directory named `ComposeFiles` in the root of the project. The `compose` role will copy all files from this directory to `/home/{{ ansible_user }}/compose/` on the target machine. Place your `docker-compose.yml` files here.

## Usage

To run the full playbook and apply all configurations, execute the following command:

```bash
ansible-playbook site.yml
```

### Dry Run

To see what changes the playbook would make without actually applying them, use the `--check` flag:

```bash
ansible-playbook site.yml --check
```

## Roles Breakdown

This playbook is organized into the following roles:

*   ### `common`
    *   **Purpose**: Handles base system setup.
    *   **Tasks**:
        *   Performs a system-wide package update and upgrade (`apt` for Debian, `dnf` for Fedora).
        *   Installs essential packages like `curl`, `git`, `vim`, `gnupg`, etc.

*   ### `docker`
    *   **Purpose**: Installs the Docker engine and related tools.
    *   **Tasks**:
        *   Adds the official Docker GPG key and package repository.
        *   Installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, and `docker-compose-plugin`.
    *   **Handlers**:
        *   Starts and enables the `docker` service on system boot.

*   ### `tailscale`
    *   **Purpose**: Installs the Tailscale VPN client.
    *   **Tasks**:
        *   Adds the official Tailscale GPG key and package repository.
        *   Installs the `tailscale` package.
    *   **Handlers**:
        *   Starts and enables the `tailscale` service on system boot.

*   ### `compose`
    *   **Purpose**: Deploys applications using Docker Compose.
    *   **Tasks**:
        *   Copies all files from the local `ComposeFiles/` directory to the remote server.
        *   Runs `docker-compose up` to start all services defined in the compose files.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) for details.
