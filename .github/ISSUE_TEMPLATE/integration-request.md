---
name: Integration Request
about: Suggest a new integration
title: "[Integration]:"
labels: ''
assignees: ''

---

## Service                                                                                      
                                                                                                 
 Name and brief description of the service and what it enables agents to do.                     
                                                                                                 
 **Description:** [e.g., "API key for Slack Bot" — short one-liner for the credential spec]      
                                                                                                 
 ## Credential Identity                                                                          
                                                                                                 
 - **credential_id:** [e.g., `slack`]                                                            
 - **env_var:** [e.g., `SLACK_BOT_TOKEN`]                                                        
 - **credential_key:** [e.g., `access_token`, `api_key`, `bot_token`]                            
                                                                                                 
 ## Tools                                                                                        
                                                                                                 
 Tool function names that require this credential:                                               
                                                                                                 
 - [e.g., `slack_send_message`]                                                                  
 - [e.g., `slack_list_channels`]                                                                 
                                                                                                 
 ## Auth Methods                                                                                 
                                                                                                 
 - **Direct API key supported:** Yes / No                                                        
 - **Aden OAuth supported:** Yes / No                                                            
                                                                                                 
 If Aden OAuth is supported, describe the OAuth scopes/permissions required.                     
                                                                                                 
 ## How to Get the Credential                                                                    
                                                                                                 
 Link where users obtain the key/token:                                                          
                                                                                                 
 [e.g., https://api.slack.com/apps]                                                              
                                                                                                 
 Step-by-step instructions:                                                                      
                                                                                                 
 1. Go to ...                                                                                    
 2. Create a ...                                                                                 
 3. Select scopes/permissions: ...                                                               
 4. Copy the key/token                                                                           
                                                                                                 
 ## Health Check                                                                                 
                                                                                                 
 A lightweight API call to validate the credential (no writes, no charges).                      
                                                                                                 
 - **Endpoint:** [e.g., `https://slack.com/api/auth.test`]                                       
 - **Method:** [e.g., `GET` or `POST`]                                                           
 - **Auth header:** [e.g., `Authorization: Bearer {token}` or `X-Api-Key: {key}`]                
 - **Parameters (if any):** [e.g., `?limit=1`]                                                   
 - **200 means:** [e.g., key is valid]                                                           
 - **401 means:** [e.g., invalid or expired]                                                     
 - **429 means:** [e.g., rate limited but key is valid]                                          
                                                                                                 
 ## Credential Group                                                                             
                                                                                                 
 Does this require multiple credentials configured together? (e.g., Google Custom Search needs   
 both an API key and a CSE ID)                                                                   
                                                                                                 
 - [ ] No, single credential                                                                     
 - [ ] Yes — list the other credential IDs in the group:                                         
                                                                                                 
 ## Additional Context                                                                           
                                                                                                 
 Links to API docs, rate limits, free tier availability, or anything else relevant.
