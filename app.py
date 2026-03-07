import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Daily Activity Tracker", layout="centered")

# --- 1. GOOGLE SHEETS CONNECTION SETUP ---
@st.cache_resource
def init_connection():
    secret_dict = dict(st.secrets["gcp_service_account"])
    client = gspread.service_account_from_dict(secret_dict)
    return client

# --- 2. FETCH MASTER DATA ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        client = init_connection()
        sheet = client.open("Office_Timesheet_App_Data")
        
        clients_records = sheet.worksheet("Client_Master").get_all_records()
        tasks_records = sheet.worksheet("Task_Master").get_all_records()
        emp_records = sheet.worksheet("Employee_Master").get_all_records()
        
        active_employees = [
            emp for emp in emp_records 
            if str(emp.get('Status', 'Active')).strip().lower() == 'active'
        ]
        
        clients_list = [f"{row['Client_Name']} (DIN: {row['DIN']})" if row.get('DIN') else row['Client_Name'] for row in clients_records]
        tasks_list = [row['Task_Category'] for row in tasks_records]
        
        st.sidebar.success("✅ Connected to Google Sheets!")
        return clients_list, tasks_list, active_employees

    except Exception as e:
        st.sidebar.warning(f"⚠️ Google Sheets Connection Failed: {e}")
        dummy_emps = [{"Employee_ID": "EMP01", "Full_Name": "Rahul S.", "Password": "1234", "Status": "Active"}]
        return ["ABC Private Limited (DIN: 01234567)"], ["GST Audit"], dummy_emps

# --- NEW: CACHED DUPLICATE CHECK TO FIX 429 ERROR ---
@st.cache_data(ttl=60) # Caches the result for 60 seconds to stop spamming the API
def check_submission_status(check_date, emp_name):
    try:
        client = init_connection()
        logs_sheet = client.open("Office_Timesheet_App_Data").worksheet("Daily_Logs")
        
        # get_all_values() uses 1 single read request instead of multiple
        all_data = logs_sheet.get_all_values() 
        
        for row in all_data:
            # Matches the date (col 0) and the employee name (col 1)
            if len(row) >= 2 and row[0] == str(check_date) and row[1] == emp_name:
                return True
        return False
    except Exception:
        return False

clients, tasks, employees = get_master_data()

emp_dict = {f"{emp['Full_Name']} ({emp['Employee_ID']})": str(emp.get('Password', '1234')) for emp in employees}
emp_names = list(emp_dict.keys())

# --- 3. SESSION STATE INITIALIZATION ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = ""
if 'activity_count' not in st.session_state:
    st.session_state.activity_count = 1

def add_activity():
    st.session_state.activity_count += 1

def remove_activity():
    if st.session_state.activity_count > 1:
        st.session_state.activity_count -= 1

# --- 4. LOGIN PORTAL ---
if not st.session_state.logged_in:
    st.title("🔐 Office Portal Login")
    st.write("Please select your name and enter your password to access the tracker.")
    
    if not emp_names:
        st.error("No active employees found. Please check your Master Sheet.")
    else:
        with st.form("login_form"):
            selected_emp = st.selectbox("Select Employee", emp_names)
            emp_password = st.text_input("Password / PIN", type="password")
            submit_login = st.form_submit_button("Login", type="primary", use_container_width=True)
            
            if submit_login:
                if emp_password == emp_dict[selected_emp]:
                    st.session_state.logged_in = True
                    st.session_state.current_user = selected_emp
                    st.rerun() 
                else:
                    st.error("Incorrect Password. Please try again.")

# --- 5. THE MAIN APPLICATION ---
else:
    st.sidebar.write(f"👤 Logged in as: **{st.session_state.current_user}**")
    
    with st.sidebar.expander("⚙️ Settings & Security"):
        st.write("**Change Your PIN**")
        new_pin = st.text_input("New PIN", type="password", key="new_pin")
        confirm_pin = st.text_input("Confirm New PIN", type="password", key="confirm_pin")
        
        if st.button("Update PIN", use_container_width=True):
            if new_pin and new_pin == confirm_pin:
                try:
                    emp_id = st.session_state.current_user.split("(")[-1].strip(")")
                    client = init_connection()
                    sheet = client.open("Office_Timesheet_App_Data").worksheet("Employee_Master")
                    
                    cell = sheet.find(emp_id)
                    if cell:
                        header = sheet.row_values(1)
                        if "Password" in header:
                            pwd_col = header.index("Password") + 1
                            sheet.update_cell(cell.row, pwd_col, new_pin)
                            st.success("PIN updated successfully!")
                            get_master_data.clear() 
                        else:
                            st.error("Error: 'Password' column not found in Master Sheet.")
                except Exception as e:
                    st.error(f"Failed to update PIN: {e}")
            else:
                st.error("PINs do not match or are empty.")

    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.rerun()

    st.title("Daily Activity & Conveyance Tracker")
    st.write("Log your daily attendance and the specific tasks you performed.")
    st.divider()

    date_logged = st.date_input("Select Date", date.today())
    
    # --- DUPLICATE SUBMISSION CHECK (NOW USING THE CACHED FUNCTION) ---
    already_submitted = check_submission_status(str(date_logged), st.session_state.current_user)

    if already_submitted:
        st.success(f"✅ You have already successfully submitted your logs for {date_logged}.")
        st.info("If you need to make corrections, please contact the administrator.")
        
    else:
        st.subheader("Shift Details")

        hours = [f"{i:02d}" for i in range(1, 13)]
        mins = [f"{i:02d}" for i in range(0, 60)]
        ampm = ["AM", "PM"]

        col1, col2 = st.columns(2)
        with col1:
            st.write("**In Time**")
            h_in, m_in, p_in = st.columns(3)
            in_time_h = h_in.selectbox("Hour", hours, key="in_h")
            in_time_m = m_in.selectbox("Min", mins, key="in_m")
            in_time_p = p_in.selectbox("AM/PM", ampm, key="in_p")
            final_in_time = f"{in_time_h}:{in_time_m} {in_time_p}"

        with col2:
            st.write("**Out Time**")
            h_out, m_out, p_out = st.columns(3)
            out_time_h = h_out.selectbox("Hour", hours, key="out_h")
            out_time_m = m_out.selectbox("Min", mins, key="out_m")
            out_time_p = p_out.selectbox("AM/PM", ["PM", "AM"], key="out_p") 
            final_out_time = f"{out_time_h}:{out_time_m} {out_time_p}"

        st.divider()

        st.subheader("Activities Performed")
        st.info("💡 **Tip:** You can click the 'Select Client' box and start typing to instantly search.")

        logs_to_submit = []
        validation_passed = True

        for i in range(st.session_state.activity_count):
            st.markdown(f"### Activity {i + 1}")
            
            c_client = st.selectbox("Select Client", clients, key=f"client_{i}")
            c_tasks = st.multiselect("Select Task(s) Performed", tasks, key=f"tasks_{i}")
            c_desc = st.text_area("Detailed Task Description", key=f"desc_{i}")
            c_loc = st.radio("Work Location", ["Office", "Client Place"], horizontal=True, key=f"loc_{i}")
            
            c_visit_loc = ""
            c_conv = 0
            if c_loc == "Client Place":
                c_visit_loc = st.selectbox("Client Location Visited", clients, key=f"visit_loc_{i}")
                c_conv = st.number_input("Conveyance Claimed (₹)", min_value=0, key=f"conv_{i}")
                
            st.markdown("---") 
            
            tasks_string = ", ".join(c_tasks) if c_tasks else ""
            
            row_data = [
                str(date_logged), 
                st.session_state.current_user, 
                final_in_time, 
                final_out_time, 
                c_loc, 
                c_client, 
                tasks_string, 
                c_desc, 
                c_visit_loc, 
                c_conv
            ]
            logs_to_submit.append(row_data)

            if not c_tasks or not c_desc:
                validation_passed = False
            if c_loc == "Client Place" and not c_visit_loc:
                validation_passed = False

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            st.button("➕ Add Another Activity", on_click=add_activity, use_container_width=True)
        with col_btn2:
            st.button("➖ Remove Last Activity", on_click=remove_activity, disabled=(st.session_state.activity_count == 1), use_container_width=True)

        st.write("") 
        if st.button("🚀 Submit All Logs for Today", type="primary", use_container_width=True):
            if not validation_passed:
                st.error("Please make sure all tasks have a description, at least one task category selected, and location details if it was a client visit.")
            else:
                try:
                    client = init_connection()
                    sheet = client.open("Office_Timesheet_App_Data").worksheet("Daily_Logs")
                    sheet.append_rows(logs_to_submit)
                    
                    st.success("✅ All logs submitted successfully to Google Sheets!")
                    st.balloons()
                    
                    # Force the app to forget the old submission status so the user immediately sees the success lock screen
                    check_submission_status.clear()
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Could not save to Google Sheets. Error: {e}")