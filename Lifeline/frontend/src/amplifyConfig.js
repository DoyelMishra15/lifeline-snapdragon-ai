import { Amplify } from 'aws-amplify'

const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID
const userPoolClientId = import.meta.env.VITE_COGNITO_CLIENT_ID

export function configureAmplify() {
  if (!userPoolId || !userPoolClientId) return // mock mode — nothing to configure
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
      },
    },
  })
}
