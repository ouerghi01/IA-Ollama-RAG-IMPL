from tools import *
origins = [
    "http://192.168.100.66:3000/",
    "http://localhost:3000/",
]



app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
async def startup_event():
    print("Starting up")
    global session, Retrieval, qa, templates
    session=await run_in_threadpool(initialize_database_session)
    templates = Jinja2Templates(directory="templates")
    if default_path_file.exists():
        Retrieval = create_retriever_from_documents(session, load_pdf_documents())
        qa = await run_in_threadpool(build_q_a_process,Retrieval, model_name)

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down")
    global session
    if session:
        session.shutdown()
        session = None

@app.get("/")
async def main_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/uploadfile/")
async def upload_file(file: Annotated[UploadFile, File(description="A file read as UploadFile")]):
    global default_path_file, Retrieval, qa
    file_path = UPLOAD_DIR / file.filename
    if file_path.exists():
        return {"message": file.filename + " already exists"}
    
    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    default_path_file = file_path
    Retrieval = create_retriever_from_documents(session, load_pdf_documents())
    qa = build_q_a_process(Retrieval, model_name)
    
    return {"message": file.filename + " has been uploaded"}

@app.post("/model_name/") 
async def set_model_name(request: Request, model: str = Form(...)):
    global model_name , qa
    
    model_name = model
    if qa is not None:
        qa = build_q_a_process(Retrieval, model_name)
    return {"message": f"Model name has been set to {model_name}"}
@app.get("/evaluate_response/")
async def evaluate_response(_: Request, partition_id: str, evaluation: bool):
    query=f"UPDATE store_key.response_table SET evaluation={evaluation} WHERE partition_id={partition_id}"
    session.execute(query)
    #return templates.TemplateResponse("index.html", {"request": request})
@app.post("/send_message/")
async def send_message(request: Request, question: str = Form(...)):
    find_reponse_query="SELECT * FROM store_key.response_table WHERE question=%s AND evaluation=true ALLOW FILTERING"
    result_set = session.execute(find_reponse_query, (question,))
    response = result_set[0] if result_set else None
    
    if response!="" and response is not None:
        return templates.TemplateResponse(
        "messages.html",
        {"request": request, "answer": response.answer, "question": question,"partition_id":response.partition_id,"timestamp":response.timestamp,"evaluation":True}
    )
    query=question
    query_sql = 'SELECT question, answer FROM store_key.response_table WHERE partition_id >= minTimeuuid(0) LIMIT 5  ALLOW FILTERING'

    result_set = session.execute(query_sql)
    print(result_set)
    chat_history = []
    for row in result_set:
        chat_history.append(("human",row.question))
        chat_history.append(("assistant",row.answer))
    final_answer= qa.invoke({"input": query, "chat_history": chat_history})

    if session is not None:
        partition_id = uuid.uuid1()
        now=datetime.now()
        session.execute(
        "INSERT INTO store_key.response_table (partition_id, question, answer,timestamp,evaluation) VALUES (%s, %s, %s, %s,false)",
        (partition_id,question, final_answer["answer"],now)
        )
    

    return templates.TemplateResponse(
        "messages.html",
        {"request": request, "answer": final_answer["answer"], "question": question,"partition_id":partition_id,"timestamp":now,"evaluation":False}
    )
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
# https://github.com/bhattbhavesh91/pdf-qa-astradb-langchain/blob/main/requirements.txt
# https://github.com/michelderu/chat-with-your-data-in-cassandra/blob/main/docker-compose.yml