FROM jenkins/jenkins:lts-jdk21
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv curl unzip && rm -rf /var/lib/apt/lists/*
ARG TERRAFORM_VERSION=1.13.5
RUN case "$(uname -m)" in x86_64) TF_ARCH=amd64 ;; aarch64) TF_ARCH=arm64 ;; *) exit 1 ;; esac && \
    curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip" -o /tmp/terraform.zip && \
    curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" -o /tmp/checksums && \
    EXPECTED="$(awk -v f="terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip" '$2 == f {print $1}' /tmp/checksums)" && \
    test -n "$EXPECTED" && printf '%s  /tmp/terraform.zip\n' "$EXPECTED" | sha256sum -c - && \
    unzip /tmp/terraform.zip terraform -d /usr/local/bin && rm /tmp/terraform.zip /tmp/checksums
COPY pyproject.toml /opt/clouddesk/
COPY clouddesk /opt/clouddesk/clouddesk
RUN python3 -m venv /opt/clouddesk-venv && /opt/clouddesk-venv/bin/pip install --no-cache-dir /opt/clouddesk
COPY infra /opt/clouddesk/infra
COPY Jenkinsfile /opt/clouddesk/Jenkinsfile
COPY jenkins/jenkins.yaml jenkins/jobs.groovy /opt/clouddesk/jenkins/
USER jenkins
RUN jenkins-plugin-cli --plugins workflow-aggregator configuration-as-code job-dsl credentials-binding timestamper
