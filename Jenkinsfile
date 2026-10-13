pipeline {
    agent any
    options {
        disableConcurrentBuilds()
        timeout(time: 8, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        timestamps()
    }
    parameters {
        choice(name: 'ACTION', choices: ['plan', 'apply', 'destroy'], description: 'Approved infrastructure operation')
        text(name: 'REQUEST_JSON', defaultValue: '{}', description: 'Validated CloudDesk request fields')
    }
    environment {
        PYTHONPATH = '/opt/clouddesk'
        CLOUDDESK_TF_ROOT = '/var/jenkins_home/clouddesk-state'
    }
    stages {
        stage('Run validated infrastructure operation') {
            steps {
                // Parameters are read from the environment inside Python, never inserted into shell code.
                sh '/opt/clouddesk-venv/bin/python -m clouddesk.pipeline_task'
            }
        }
        stage('Publish result') {
            steps {
                archiveArtifacts artifacts: 'result.json', fingerprint: true
            }
        }
    }
}
