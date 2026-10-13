pipelineJob('clouddesk') {
    description('Local-only storage sandbox plan, approved apply, and cleanup')
    definition {
        cps {
            script(new File('/opt/clouddesk/Jenkinsfile').text)
            sandbox()
        }
    }
}
