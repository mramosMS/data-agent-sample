@description('Name of the Container Apps environment')
param environmentId string

@description('Container image to deploy (e.g. myacr.azurecr.io/finsage-agent:latest)')
param containerImage string

@description('Azure AI Foundry project endpoint')
param foundryProjectEndpoint string

@description('Foundry model deployment name')
param foundryModelDeploymentName string = 'gpt-4o'

@description('Fabric Data Agent URL')
param dataAgentUrl string

@description('Location for all resources')
param location string = resourceGroup().location

@description('Name of the Container App')
param containerAppName string = 'finsage-agent'

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: environmentId
    configuration: {
      ingress: {
        external: false        // Internal-only — APIM is the public gateway
        targetPort: 8000
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'finsage-agent'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_MODEL_DEPLOYMENT_NAME'
              value: foundryModelDeploymentName
            }
            {
              name: 'DATA_AGENT_URL'
              value: dataAgentUrl
            }
          ]
          probes: [
            {
              type: 'Liveness'
              tcpSocket: {
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

@description('System-assigned managed identity principal ID (use to grant RBAC roles)')
output principalId string = containerApp.identity.principalId

@description('Internal FQDN of the Container App (accessible within the environment)')
output fqdn string = containerApp.properties.configuration.ingress.fqdn
