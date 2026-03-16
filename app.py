import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Daily Activity Tracker", layout="wide") 

# --- 1. GLOBAL GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def get_worksheets():
    secret_dict = dict(st.secrets["gcp_service_account"])
    client = gspread.service_account_from_dict(secret_dict)
    sh = client.open("Office_Timesheet_App_Data")
    return {
        "Client_Master": sh.worksheet("Client_Master"),
        "Task_Master": sh.worksheet("Task_Master"),
        "Employee_Master": sh.worksheet("Employee_Master"),
        "Daily_Logs": sh.worksheet("Daily_Logs")
    }

# --- 2. FETCH MASTER DATA ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        ws = get_worksheets()
        clients_records = ws["Client_Master"].get_all_records()
        tasks_records = ws["Task_Master"].get_all_records()
        emp_records = ws["Employee_Master"].get_all_records()
        
        active_employees = [
            emp for emp in emp_records 
            if str(emp.get('Status', 'Active')).strip().lower() == 'active'
        ]
        
        # Ensures DIN is always provided alongside the client name
        clients_list = [f"{row['Client_Name']} (DIN: {row['DIN']})" if row.get('DIN') else row['Client_Name'] for row in clients_records]
        tasks_list = [row['Task_Category'] for row in tasks_records]
        
        return clients_list, tasks_list, active_employees
    except Exception as e:
        st.sidebar.warning(f"⚠️ Google Sheets Connection Failed: {e}")
        return [], [], []

# --- 3. CACHED DUPLICATE CHECK ---
@st.cache_data(ttl=60) 
def check_submission_status(check_date, emp_name):
    try:
        ws = get_worksheets()
        all_data = ws["Daily_Logs"].get_all_values() 
        for row in all_data:
            if len(row) >= 2 and row[0] == str(check_date) and row[1] == emp_name:
                return True
        return False
    except Exception:
        return False

clients, tasks, employees = get_master_data()
emp_dict = {f"{emp['Full_Name']} ({emp['Employee_ID']})": str(emp.get('Password', '1234')) for emp in employees}
emp_names = list(emp_dict.keys())

# --- 4. SESSION STATE INITIALIZATION ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = ""
if 'activity_count' not in st.session_state:
    st.session_state.activity_count = 1
if 'just_submitted' not in st.session_state:
    st.session_state.just_submitted = False

def add_activity():
    st.session_state.activity_count += 1
def remove_activity():
    if st.session_state.activity_count > 1:
        st.session_state.activity_count -= 1

# --- 5. LOGIN PORTAL ---
if not st.session_state.logged_in:
    st.title("🔐 Office Portal Login")
    
    tab1, tab2 = st.tabs(["Employee Login", "Admin Login"])
    
    with tab1:
        st.write("Please select your name and enter your PIN.")
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
                        st.session_state.is_admin = False
                        st.session_state.current_user = selected_emp
                        st.session_state.just_submitted = False
                        st.rerun() 
                    else:
                        st.error("Incorrect Password. Please try again.")
                        
    with tab2:
        st.write("Office Administrator Login")
        with st.form("admin_login_form"):
            admin_pass = st.text_input("Admin Password", type="password")
            submit_admin = st.form_submit_button("Login as Admin", type="primary", use_container_width=True)
            
            if submit_admin:
                if admin_pass == "admin123": 
                    st.session_state.logged_in = True
                    st.session_state.is_admin = True
                    st.session_state.current_user = "Administrator"
                    st.rerun()
                else:
                    st.error("Incorrect Admin Password.")

# --- 6. ADMIN DASHBOARD VIEW ---
elif st.session_state.is_admin:
    st.sidebar.write("👑 **Admin Dashboard**")
    
    # --- NEW: Manual Sync Button ---
    st.sidebar.markdown("---")
    st.sidebar.write("**Admin Controls**")
    if st.sidebar.button("🔄 Sync Master Data Now", use_container_width=True):
        get_master_data.clear()
        st.sidebar.success("Lists updated successfully!")
        st.rerun()
        
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.session_state.is_admin = False
        st.rerun()
        
    st.title("📊 Office Operations Dashboard")
    st.divider()
    
    try:
        ws = get_worksheets()
        records = ws["Daily_Logs"].get_all_records()
        df = pd.DataFrame(records)
        
        if df.empty:
            st.info("No data has been logged yet.")
        else:
            df['Date'] = pd.to_datetime(df['Date'])
            df['Conveyance_₹'] = pd.to_numeric(df['Conveyance_₹'], errors='coerce').fillna(0)
            
            st.subheader("Filter Data")
            col1, col2, col3 = st.columns(3)
            with col1:
                start_date = st.date_input("Start Date", df['Date'].min())
            with col2:
                end_date = st.date_input("End Date", df['Date'].max())
            with col3:
                emp_filter = st.multiselect("Filter by Employee", options=df['Employee_ID'].unique())
            
            mask = (df['Date'].dt.date >= start_date) & (df['Date'].dt.date <= end_date)
            filtered_df = df.loc[mask]
            if emp_filter:
                filtered_df = filtered_df[filtered_df['Employee_ID'].isin(emp_filter)]
            
            st.markdown("---")
            
            st.subheader("Key Performance Indicators")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Activities Logged", len(filtered_df))
            m2.metric("Total Conveyance Claimed", f"₹{filtered_df['Conveyance_₹'].sum():.2f}")
            m3.metric("Unique Clients Serviced", filtered_df['Client_ID'].nunique())
            m4.metric("Active Employees", filtered_df['Employee_ID'].nunique())
            
            st.markdown("---")
            
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.write("**Conveyance by Employee**")
                conv_by_emp = filtered_df.groupby('Employee_ID')['Conveyance_₹'].sum().reset_index()
                if not conv_by_emp.empty:
                    st.bar_chart(conv_by_emp, x='Employee_ID', y='Conveyance_₹')
                    
            with col_chart2:
                st.write("**Work Location Breakdown**")
                loc_counts = filtered_df['Work_Location'].value_counts()
                st.bar_chart(loc_counts)
                
            st.markdown("---")
            
            # --- NEW: Export to Excel/CSV Button ---
            st.subheader("Raw Data View")
            display_df = filtered_df.copy()
            display_df['Date'] = display_df['Date'].dt.strftime('%Y-%m-%d')
            
            # Convert dataframe to CSV format for download
            csv_export = display_df.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="📥 Export Filtered Data for Payroll (CSV)",
                data=csv_export,
                file_name=f"Timesheet_Export_{start_date}_to_{end_date}.csv",
                mime="text/csv",
            )
            
            st.dataframe(display_df, use_container_width=True)
            
    except Exception as e:
        st.error(f"Error loading dashboard data: {e}")

# --- 7. THE EMPLOYEE DATA ENTRY VIEW ---
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
                    ws = get_worksheets()
                    cell = ws["Employee_Master"].find(emp_id)
                    if cell:
                        header = ws["Employee_Master"].row_values(1)
                        if "Password" in header:
                            pwd_col = header.index("Password") + 1
                            ws["Employee_Master"].update_cell(cell.row, pwd_col, new_pin)
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
        st.session_state.current_user = ""
        st.rerun()

    st.title("Daily Activity & Conveyance Tracker")
    st.write("Log your daily attendance and the specific tasks you performed.")
    st.divider()

    date_logged = st.date_input("Select Date", date.today())
    
    already_submitted = st.session_state.just_submitted or check_submission_status(str(date_logged), st.session_state.current_user)

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
                str(date_logged), st.session_state.current_user, final_in_time, final_out_time, 
                c_loc, c_client, tasks_string, c_desc, c_visit_loc, c_conv
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
                    ws = get_worksheets()
                    ws["Daily_Logs"].append_rows(logs_to_submit)
                    st.success("✅ All logs submitted successfully to Google Sheets!")
                    st.balloons()
                    st.session_state.just_submitted = True
                    check_submission_status.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not save to Google Sheets. Error: {e}")