import streamlit as st  
from streamlit_feedback import streamlit_feedback  
import uuid  

from azure.cosmos import CosmosClient
import json
from openai import AzureOpenAI
import requests
import datetime
import pandas as pd
from app_func_desc import func_desc
from app_secrets import azure_api_key, azure_endpoint, azure_api_version, cosmos_db_api_key, cosmos_db_url, model
from data_extractor import retrieve_prompt, update_vectorstore
from cosmos_status import get_latest_db_info


# gpt-4
client = AzureOpenAI(
    api_version= azure_api_version,
    api_key=azure_api_key,
    base_url= azure_endpoint
)

st.title("CosmosQnA-V5")


# Initialize session state variables if they do not exist  
if 'question_state' not in st.session_state:  
    st.session_state.question_state = False  
  
if 'fbk' not in st.session_state:  
    st.session_state.fbk = str(uuid.uuid4())  
  
if "chat_history" not in st.session_state:  
    st.session_state.chat_history = []  

if "chat_prompt" not in st.session_state:  
    st.session_state.chat_prompt = [{"role": "system", "content": "You are an AI assistant that helps people find information."}]  
  
if 'show_feedback_text' not in st.session_state:  
    st.session_state.show_feedback_text = False  
  
if 'detailed_feedback' not in st.session_state:  
    st.session_state.detailed_feedback = {}  

def display_answer():  
    """  
    Display the chat history along with any feedback provided by the user.  
    """  
    for entry in st.session_state.chat_history:  
        # Display the user's question  
        with st.chat_message("human"):  
            st.write(entry["question"])  
        # Display the AI's answer  
        with st.chat_message("ai"):  
            st.write(entry["answer"])  
  
        # Display feedback if available  
        if "feedback" in entry:  
            st.write(f"Feedback: {entry['feedback']}")  
            # If detailed feedback is provided, display it as well
            if entry.get("feedback") == "👎" and "detailed_feedback" in entry:  
                st.write(f"Additional Feedback: {entry['detailed_feedback']}")  




def connect_to_db():
    url = cosmos_db_url
    key = cosmos_db_api_key
    database_name = 'Userdb2'
    container_name = 'user_data'

    database_client = CosmosClient(url, credential=key)
    database = database_client.get_database_client(database_name)
    container = database.get_container_client(container_name)
    return container




# get completions

def get_completion(messages=None, func=None, function_call="auto",
                temperature=0, max_tokens=1000, top_p=1, frequency_penalty=0,
                presence_penalty=0, stop=None):
    # Set default values if parameters are not provided
    messages = messages or []
    functions = func or []
    
    # Make API call with provided parameters
    response = client.chat.completions.create(
        messages= messages,
        model=model,
        functions=func,
        function_call=function_call,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        stop=stop
    )
    return response.choices[0].message


def tot_agent(user_query):
    # return None
    # print("Sending request to Creative Tool.")
    endpoint_url = "https://querygeneratortot.azurewebsites.net/api/TriggerCosmosTOT?code=VJmfGFxZTvZxpXOGthDL5DFFTYuXwzfl9NeDhPoCIUk2AzFuRGjDNw=="  # Replace with your actual endpoint URL

    try:
        # Send a POST request to the Azure Web App Service
        response = requests.post(endpoint_url, json=user_query)
        # print("tot response")
        print(f"tot response: {type(response.json())}")
        # print(type(response.json()))
        # print(dict(response.json()))
        # Check if the request was successful (HTTP status code 200)
        if response.status_code == 200:
            # print("Successfully called Creative tool")
            # Parse the JSON response from the server
            response_data = response.json()


            return json.loads(response_data)
            # return dict(response_data)

        else:
            print(f"Request failed with status code {response.status_code}")
            return None

    except Exception as e:
        # print(response.content)
        print(f"An error occurred while making the request: {e}")
        return None


def connect_and_query_db(container, db_query):  
    try:  
        items = list(container.query_items(  
            query=db_query,   
            enable_cross_partition_query=True  
        ))
        return items

    except Exception as e:  
        print(f"Error occurred: {e}")  
        return None



def load_query(kwargs):
    return json.loads(kwargs)



def call_tot_agent(user_query):
    # modified_query = modify_query(user_query)
    user_query = {"user_query": user_query}
    response_data = tot_agent(user_query)
    return response_data


def process_response(container, response_data):
    if "response_message" in response_data:
        # print("ResponseData\n\n")
        # print(response_data["response_message"])
        return None, response_data["response_message"]
    elif "database_query" in response_data:
        new_items = connect_and_query_db(container, response_data["database_query"])
        # print("ResponseData\n\n")
        # print(str(new_items))
        return response_data["database_query"],(str(new_items))[:5000] + "..."
    else:
        return None, None


def execute_query(kwargs):
    # Load json string to python dictionary
    kwargs = load_query(kwargs)

    # Extract user query and database query from the dictionary
    modified_question = kwargs["modified_question"]
    database_query = kwargs["database_query"]

    # Establish connection to the database  
    container = connect_to_db()

    # Try to fetch items from the database using the provided query  
    items = connect_and_query_db(container, database_query)
    # print(items)

    # If items are found in the database, return them  
    if items and len(items) > 0:
        return database_query, (str(items))[:5000] + "..."
    else:  
        # If no items found in the database, call the TOT agent  
        print("Calling TOT agent")
        response_data = call_tot_agent(modified_question)
        print(f"response_data: {response_data}")

        # Process the response data
        return process_response(container, response_data)


def get_power_user():
    container = connect_to_db()
    
    # Get current date
    current_date = datetime.datetime.now()
    
    # Calculate the date range for the last 15 days
    start_date = current_date - datetime.timedelta(days=15)
    end_date = current_date
    
    # Format dates for the query
    start_date_str = start_date.strftime('%m/%d/%Y')
    end_date_str = end_date.strftime('%m/%d/%Y')
    
    # Query data for the last 15 days
    query = f"SELECT c.email, c.questions, c.timestamp FROM c WHERE udf.parseDate(c.timestamp)>=udf.parseDate('{start_date_str}') AND udf.parseDate(c.timestamp)<=udf.parseDate('{end_date_str}')"
    
    results = list(container.query_items(
        query=query,
        enable_cross_partition_query=True
    ))

    # Convert results to pandas DataFrame
    df = pd.DataFrame(results)

    # Transform questions column to its length
    df['questions'] = df['questions'].apply(len)

    # Group by email and sum questions
    df_grouped = df.groupby('email')['questions'].sum().reset_index()

    # Sort DataFrame by questions in descending order
    df_grouped = df_grouped.sort_values(by='questions', ascending=False)

    return str(df_grouped)


def get_answer():
    message = st.session_state.chat_prompt.copy()

    user_query_dict = message.pop()

    message.append({"role": "user", "content": get_latest_db_info()})
    message.append({"role": "assistant", "content": "Thank you for sharing the latest database status."})
    message.append(user_query_dict)


    print("Generating First Response")

    with st.spinner("Thinking..."):
        response = get_completion(messages=message, func=func_desc)
        # print(response)

        while True:
            if response.function_call:
                response.content = "null"
                message.append(response)
                function_name = response.function_call.name

                if function_name == "execute_query":
                    print("execute_query")
                    print(response.function_call.arguments)

                    with st.expander("Generated NoSQL Query"):
                        nosql_query,function_response = execute_query(response.function_call.arguments)

                        st.write(nosql_query)

                    message.append({
                        "role": "function",
                        "name": function_name,
                        "content": str(function_response),
                    })

                    # print(function_response)

                    print("generating response after function call")

                    response = get_completion(messages=message, func=func_desc)
                    # print(response)

                    continue

                elif function_name == "get_power_user":
                    print("getting power user")
                    # print(function_response)

                    with st.expander("Extracting Power Users"):
                        function_response = get_power_user()
                        st.write(function_response)

                    message.append({
                        "role": "function",
                        "name": function_name,
                        "content": str(function_response),
                    })

                    # print(function_response)

                    print("generating response after function call")

                    response = get_completion(messages=message, func=func_desc)
                    # print(response)

                    continue


            else:
                print("Returning Final Response")
                # st.session_state.messages.append({"role": "assistant", "content": response.content})

                # print(response)
                return response.content

  
def create_answer(question):  
    """  
    Create an answer for the given question and add it to the chat history.  
    :param question: The question asked by the user.  
    """  
    if question is None:  
        return  
  
    # Generate a unique message ID based on the length of chat history  
    message_id = len(st.session_state.chat_history)  
    # Append the question and a placeholder answer to the chat history

    system_prompt = retrieve_prompt(question)

    # system_prompt = "jhasbd"

    st.session_state.chat_prompt[0] = {"role": "system", "content": system_prompt}

    st.session_state.chat_prompt.append({"role": "user", "content": question})

    answer = get_answer()

    st.session_state.chat_history.append({  
        "question": question,  
        "answer": answer,  
        "message_id": message_id,  
    })

    st.session_state.chat_prompt.append({"role": "assistant", "content": answer})
  
def fbcb(response):  
    """  
    Callback function to handle feedback submission.  
    :param response: The feedback response provided by the user.  
    """  
    # Update the last chat entry with the provided feedback  
    last_entry = st.session_state.chat_history[-1]  
    last_entry.update({'feedback': response})  
  
    # If thumbs down, prompt for detailed feedback  
    if response == "👎":  
        st.session_state.show_feedback_text = True  
    else:  
        st.session_state.show_feedback_text = False  
  
    # Refresh the feedback key to reset the feedback component  
    st.session_state.fbk = str(uuid.uuid4())  
  
# Start of the main application  
question = st.chat_input("Ask your question here .... !!!!", key="question_input")  
if question:  
    st.session_state.question_state = True  
  
if st.session_state.question_state:  
    # Create an answer for the provided question  
    create_answer(question)  
    # Display the chat history with any feedback  
    display_answer()  
  
    # Capture feedback using the streamlit_feedback component  
    streamlit_feedback(  
        feedback_type="thumbs",  
        optional_text_label="[Optional]",  
        align="flex-start",  
        key=st.session_state.fbk,  
        on_submit=fbcb  
    )  
  
    # # If thumbs down was selected, show text input for detailed feedback  
    # if st.session_state.show_feedback_text:  
    #     with st.form("feedback_form"):  
    #         # Text area for user to provide detailed feedback  
    #         detailed_feedback = st.text_area("Please provide the accurate database query:")  
    #         # Button to submit the detailed feedback  
    #         submit_button = st.form_submit_button(label="Submit Detailed Feedback")  
  
    #         # If detailed feedback is submitted, update the last chat entry  
    #         if submit_button and detailed_feedback:  
    #             last_entry = st.session_state.chat_history[-1]  
    #             last_entry.update({'detailed_feedback': detailed_feedback})  
    #             st.session_state.show_feedback_text = False  
    #             # Update the display after submitting detailed feedback  
    #             display_answer()  
  
# Clear the input field after processing the input to avoid repeated submissions  
if 'question_input' in st.session_state:  
    del st.session_state['question_input']  
