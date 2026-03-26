import streamlit as st
import pandas as pd
import gspread
from datetime import date, datetime, time
import pytz
import math
from google.oauth2.service_account import Credentials
from streamlit_geolocation import streamlit_geolocation

st.set_page_config(page_title="Daily Activity Tracker", layout="wide") 

# --- OFFICE EXACT COORDINATES ---
OFFICE_LAT = 13.034167
OFFICE_LON = 80.212861

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000  
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_current_ist_time():
    ist_timezone = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist_timezone).strftime("%H:%M")

@st.cache_resource
def get_worksheets():
    secret_dict = dict(st.secrets["gcp_service_account"])
    client = gspread.service_account_from_dict(secret_dict)
    sh = client.open("Office_Timesheet_App_Data")
    
    try:
        return {
            "Client_Master": sh.worksheet("Client_Master"),
            "Task_Master": sh.worksheet("Task_Master"),
            "Employee_Master": sh.worksheet("Employee_Master"),
            "Daily_Logs": sh.worksheet("Daily_Logs"),
            "Attendance_Log": sh.worksheet("Attendance_Log") 
        }
    except gspread.exceptions.WorksheetNotFound:
        st.error("⚠️ CRITICAL: Could not find the 'Attendance_Log' tab.")
        st.stop()

@st.cache_data(ttl=600)
def get_master_data():
    ws = get_worksheets()
    clients_records = ws["Client_Master"].get_all_records()
    tasks_records = ws["Task_Master"].get_all_records()
    emp_records = ws["Employee_Master"].get_all_records()
    
    active_employees = [emp for emp in emp_records if str(emp.get('Status', 'Active')).strip().lower() == 'active']
    tasks_list = [row['Task_Category'] for row in tasks_records]
    
    clients_list = []
    client_coords = {} 
    
    for row in clients_records:
        name = f"{row['Client_Name']} (DIN: {row['DIN']})" if row.get('DIN') else row['Client_Name']
        clients_list.append(name)
        lat = str(row.get('Latitude', '')).strip()
        lon = str(row.get('Longitude', '')).strip()
        try:
            client_coords[name] = (float(lat) if lat else None, float(lon) if lon else None)
        except ValueError:
            client_coords[name] = (None, None) 
            
    return clients_list, tasks_list, active_employees, client_coords

# --- ATTENDANCE ENGINE (NOW CACHED TO PREVENT CRASHES) ---
@st.cache_data(ttl=60)
def get_attendance_status(check_date, emp_name):
    ws = get_worksheets()
    records = ws["Attendance_Log"].get_all_values() 
    for row in records:
        if len(row) >= 4 and row[0] == str(check_date) and row[1] == emp_name:
            in_type = row[4] if len(row) > 4 else "Unknown"
            in_loc = row[5] if len(row) > 5 else "Unknown"
            
            if row[3] != "": 
                return "punched_out", row[2], row[3], in_type, in_loc
            else:
                return "punched_in", row[2], None, in_type, in_loc
    return "not_punched_in", None, None, None, None

def punch_in(check_date, emp_name, in_time, in_type, in_loc):
    ws = get_worksheets()
    ws["Attendance_Log"].append_row([str(check_date), emp_name, in_time, "", in_type, in_loc, ""])
    get_attendance_status.clear() # Instantly refreshes screen

def punch_out(check_date, emp_name, out_time, out_loc):
    ws = get_worksheets()
    records = ws["Attendance_Log"].get_all_values()
    for i, row in enumerate(records):
        if len(row) >= 2 and row[0] == str(check_date) and row[1] == emp_name:
            ws["Attendance_Log"].update_cell(i + 1, 4, out_time) 
            ws["Attendance_Log"].update_cell(i + 1, 7, out_loc)  
            break
    get_attendance_status.clear() # Instantly refreshes screen

@st.cache_data(ttl=60)
def get_todays_tasks(check_date, emp_name):
    ws = get_worksheets()
    records = ws["Daily_Logs"].get_all_records()
    df = pd.DataFrame(records)
    if not df.empty:
        df['Date'] = df['Date'].astype(str)
        return df[(df['Date'] == str(check_date)) & (df['Employee_ID'] == emp_name)]
    return pd.DataFrame()

clients, tasks, employees, client_coords = get_master_data()
emp_dict = {f"{emp['Full_Name']} ({emp['Employee_ID']})": str(emp.get('Password', '1234')) for emp in employees}
emp_names = list(emp_dict.keys())

# --- SESSION STATE ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'is_admin' not in st.session_state: st.session_state.is_admin = False
if 'current_user' not in st.session_state: st.session_state.current_user = ""

# --- LOGIN PORTAL ---
if not st.session_state.logged_in:
    st.title("🔐 Office Portal Login")
    tab1, tab2 = st.tabs(["Employee Login", "Admin Login"])
    
    with tab1:
        with st.form("login_form"):
            selected_emp = st.selectbox("Select Employee", emp_names)
            emp_password = st.text_input("Password / PIN", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if emp_password == emp_dict[selected_emp]:
                    st.session_state.logged_in = True
                    st.session_state.is_admin = False
                    st.session_state.current_user = selected_emp
                    st.rerun() 
                else: st.error("Incorrect Password.")
                        
    with tab2:
        with st.form("admin_login_form"):
            admin_pass = st.text_input("Admin Password", type="password")
            if st.form_submit_button("Login as Admin", type="primary", use_container_width=True):
                if admin_pass == "admin123": 
                    st.session_state.logged_in = True
                    st.session_state.is_admin = True
                    st.session_state.current_user = "Administrator"
                    st.rerun()
                else: st.error("Incorrect Admin Password.")

# --- ADMIN DASHBOARD VIEW ---
elif st.session_state.is_admin:
    st.sidebar.write("👑 **Admin Dashboard**")
    if st.sidebar.button("🔄 Sync Master Data Now", use_container_width=True):
        get_master_data.clear()
        st.rerun()
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.session_state.is_admin = False
        st.rerun()
        
    st.title("📊 Office Operations Dashboard")
    try:
        ws = get_worksheets()
        att_df = pd.DataFrame(ws["Attendance_Log"].get_all_records())
        log_df = pd.DataFrame(ws["Daily_Logs"].get_all_records())
        
        st.subheader("🏢 Daily Attendance Overview")
        
        today_str = str(date.today())
        if not att_df.empty:
            att_df['Date'] = att_df['Date'].astype(str)
            today_att = att_df[att_df['Date'] == today_str]
            punched_in_emps = today_att['Employee_ID'].tolist() if not today_att.empty else []
        else:
            today_att = pd.DataFrame()
            punched_in_emps = []
            
        missing_emps = [emp for emp in emp_names if emp not in punched_in_emps]
        
        col_in, col_missing = st.columns(2)
        
        with col_in:
            st.markdown("### ✅ Punched In")
            if not today_att.empty:
                display_att = today_att[['Employee_ID', 'Daily_In_Time', 'Punch_In_Type', 'Daily_Out_Time']]
                st.dataframe(display_att, use_container_width=True, hide_index=True)
            else: 
                st.info("No one has punched in yet today.")
                
        with col_missing:
            st.markdown(f"### ❌ Not Punched In ({len(missing_emps)})")
            if missing_emps:
                missing_df = pd.DataFrame(missing_emps, columns=["Missing Employees"])
                st.dataframe(missing_df, use_container_width=True, hide_index=True)
            else:
                st.success("Everyone is accounted for today!")
        
        st.markdown("---")
        st.subheader("🛠️ Admin Overrides (Manual Punch Out)")
        
        if not att_df.empty:
            active_sessions = att_df[att_df['Daily_Out_Time'].astype(str).str.strip() == ""]
            
            if not active_sessions.empty:
                st.warning(f"⚠️ {len(active_sessions)} employee(s) currently have open shifts.")
                
                with st.form("admin_override_form"):
                    options = [f"{row['Employee_ID']} (Date: {row['Date']})" for _, row in active_sessions.iterrows()]
                    selected_session = st.selectbox("Select Open Timesheet", options)
                    
                    st.write("**Set Manual Out Time (24-Hour Format)**")
                    col_h, col_m = st.columns(2)
                    with col_h:
                        selected_hr = st.selectbox("Hour (00-23)", [f"{i:02d}" for i in range(24)])
                    with col_m:
                        selected_min = st.selectbox("Minute (00-59)", [f"{i:02d}" for i in range(60)])
                    
                    if st.form_submit_button("Force Punch OUT", type="primary"):
                        selected_idx = options.index(selected_session)
                        target_row = active_sessions.iloc[selected_idx]
                        target_emp = target_row['Employee_ID']
                        target_date = target_row['Date']
                        
                        formatted_time = f"{selected_hr}:{selected_min}"
                        punch_out(target_date, target_emp, formatted_time, "Admin Override (Manual)")
                        st.success(f"Successfully punched out {target_emp} for {target_date} at {formatted_time}.")
                        st.rerun()
            else:
                st.success("✅ All active shifts have been securely closed.")
            
        st.markdown("---")
        
        if not log_df.empty:
            log_df['Date'] = pd.to_datetime(log_df['Date'])
            log_df['Conveyance_₹'] = pd.to_numeric(log_df.get('Conveyance_₹', 0), errors='coerce').fillna(0)
            log_df['Time_Spent_Mins'] = pd.to_numeric(log_df.get('Time_Spent_Mins', 0), errors='coerce').fillna(0)
            
            st.subheader("Filter Task Data")
            col1, col2, col3, col4 = st.columns(4)
            with col1: start_date = st.date_input("Start Date", log_df['Date'].min())
            with col2: end_date = st.date_input("End Date", log_df['Date'].max())
            with col3: emp_filter = st.multiselect("Filter by Employee", options=log_df['Employee_ID'].unique())
            with col4: client_filter = st.multiselect("Filter by Client", options=log_df['Client_ID'].unique())
            
            mask = (log_df['Date'].dt.date >= start_date) & (log_df['Date'].dt.date <= end_date)
            filtered_df = log_df.loc[mask]
            if emp_filter: filtered_df = filtered_df[filtered_df['Employee_ID'].isin(emp_filter)]
            if client_filter: filtered_df = filtered_df[filtered_df['Client_ID'].isin(client_filter)]
            
            st.markdown("---")
            total_hours = filtered_df['Time_Spent_Mins'].sum() / 60
            
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Total Activities", len(filtered_df))
            m2.metric("Total Hours Logged", f"{total_hours:.1f} hrs")
            m3.metric("Total Conveyance", f"₹{filtered_df['Conveyance_₹'].sum():.2f}")
            m4.metric("Unique Clients", filtered_df['Client_ID'].nunique())
            m5.metric("Active Employees", filtered_df['Employee_ID'].nunique())
            
            st.markdown("---")
            st.subheader("📈 Billing & Productivity Reports")
            
            report_col1, report_col2 = st.columns(2)
            
            with report_col1:
                st.write("**Total Hours by Client**")
                client_hours = (filtered_df.groupby('Client_ID')['Time_Spent_Mins'].sum() / 60).reset_index()
                client_hours.rename(columns={'Time_Spent_Mins': 'Hours'}, inplace=True)
                if not client_hours.empty: st.bar_chart(client_hours, x='Client_ID', y='Hours')
                
            with report_col2:
                st.write("**Total Hours by Task Category**")
                if not filtered_df.empty:
                    expanded_tasks = filtered_df.assign(Single_Task=filtered_df['Tasks'].str.split(', ')).explode('Single_Task')
                    task_hours = (expanded_tasks.groupby('Single_Task')['Time_Spent_Mins'].sum() / 60).reset_index()
                    task_hours.rename(columns={'Time_Spent_Mins': 'Hours'}, inplace=True)
                    st.bar_chart(task_hours, x='Single_Task', y='Hours')
            
            st.markdown("---")
            
            col_chart1, col_chart2, col_chart3 = st.columns(3)
            with col_chart1:
                st.write("**Hours Logged by Employee**")
                time_by_emp = (filtered_df.groupby('Employee_ID')['Time_Spent_Mins'].sum() / 60).reset_index()
                time_by_emp.rename(columns={'Time_Spent_Mins': 'Hours'}, inplace=True)
                if not time_by_emp.empty: st.bar_chart(time_by_emp, x='Employee_ID', y='Hours')
            
            with col_chart2:
                st.write("**Conveyance by Employee**")
                conv_by_emp = filtered_df.groupby('Employee_ID')['Conveyance_₹'].sum().reset_index()
                if not conv_by_emp.empty: st.bar_chart(conv_by_emp, x='Employee_ID', y='Conveyance_₹')
                
            with col_chart3:
                st.write("**Work Location Breakdown**")
                loc_counts = filtered_df['Work_Location'].value_counts()
                st.bar_chart(loc_counts)
            
            st.markdown("---")
            st.subheader("Raw Data View")
            display_df = filtered_df.copy()
            display_df['Date'] = display_df['Date'].dt.strftime('%Y-%m-%d')
            
            csv_export = display_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Filtered Data for Payroll (CSV)",
                data=csv_export,
                file_name=f"Timesheet_Export_{start_date}_to_{end_date}.csv",
                mime="text/csv",
            )
            
            st.dataframe(display_df, use_container_width=True)
            
    except Exception as e: st.error(f"Error loading dashboard: {e}")

# --- THE EMPLOYEE LIVE ENTRY VIEW ---
else:
    st.sidebar.write(f"👤 Logged in as: **{st.session_state.current_user}**")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.session_state.current_user = ""
        st.rerun()

    st.title("Live Activity Tracker")
    current_date = date.today()
    st.write(f"**Date:** {current_date}")
    st.divider()
    
    status, in_time, out_time, in_type, in_loc = get_attendance_status(current_date, st.session_state.current_user)

    # PHASE 1: PUNCH IN GATE
    if status == "not_punched_in":
        st.warning("You have not punched in for the day yet.")
        st.subheader("Start Your Shift")
        
        punch_type = st.radio("Where are you punching in from?", ["Office", "Client Place"])
        visit_loc = "Office"
        
        if punch_type == "Client Place":
            visit_loc = st.selectbox("Select Client Location", clients)
            
        st.write("**📍 GPS Verification Required**")
        st.info("Please capture your location to unlock your timesheet for the day.")
        user_location = streamlit_geolocation()
        
        if st.button("⏱️ Verify Location & Punch IN", type="primary", use_container_width=True):
            if user_location is None or user_location.get('latitude') is None:
                st.error("⚠️ Please capture your GPS location using the button above.")
            else:
                is_valid = True
                final_loc_str = visit_loc
                u_lat, u_lon = user_location['latitude'], user_location['longitude']
                
                if punch_type == "Office":
                    dist = calculate_distance(u_lat, u_lon, OFFICE_LAT, OFFICE_LON)
                    if dist > 100:
                        st.error(f"❌ Verification Failed: You are {int(dist)} meters away from the Office.")
                        is_valid = False
                else:
                    t_lat, t_lon = client_coords.get(visit_loc, (None, None))
                    if t_lat is None:
                        final_loc_str += " (Geo-Fence Skipped: Missing)"
                    else:
                        dist = calculate_distance(u_lat, u_lon, t_lat, t_lon)
                        if dist > 200:
                            st.error(f"❌ Verification Failed: You are {int(dist)} meters away from the Client.")
                            is_valid = False
                            
                if is_valid:
                    auto_in_time = get_current_ist_time()
                    punch_in(current_date, st.session_state.current_user, auto_in_time, punch_type, final_loc_str)
                    st.rerun()

    # PHASE 2: ACTIVE SHIFT
    elif status == "punched_in":
        st.success(f"🟢 **Active Shift:** Punched In at {in_time} from **{in_loc}**")
        
        with st.container(border=True):
            st.subheader("Log a Completed Task")
            c_client = st.selectbox("Select Client for this Task", clients)
            c_tasks = st.multiselect("Select Task(s) Performed", tasks)
            c_desc = st.text_area("Detailed Task Description")
            
            col_dur, col_conv = st.columns(2)
            with col_dur:
                c_time = st.number_input("Time Spent on Task (in minutes)", min_value=1, step=5, value=30)
            with col_conv:
                c_conv = st.number_input("Conveyance Claimed for this task (₹)", min_value=0)
                
            if st.button("➕ Submit Task", type="primary"):
                if not c_tasks or not c_desc:
                    st.error("Tasks and Description are required.")
                else:
                    tasks_string = ", ".join(c_tasks)
                    row_data = [str(current_date), st.session_state.current_user, "-", "-", in_type, c_client, tasks_string, c_desc, in_loc, c_conv, c_time]
                    get_worksheets()["Daily_Logs"].append_row(row_data)
                    st.success("Task Logged Successfully!")
                    get_todays_tasks.clear() # Instantly refreshes task table
                    st.rerun()

        st.subheader("📋 Your Tasks Today")
        todays_df = get_todays_tasks(current_date, st.session_state.current_user)
        if not todays_df.empty:
            view_df = todays_df.drop(columns=['In_Time', 'Out_Time', 'Employee_ID', 'Date'], errors='ignore')
            st.dataframe(view_df, use_container_width=True)
            
        st.divider()
        
        st.subheader("End Your Shift")
        st.write("Ready to leave? You must verify your location one last time to securely lock your timesheet.")
        
        out_location = streamlit_geolocation()
        
        if st.button("🛑 Verify Location & Punch OUT", type="primary", use_container_width=True):
            if out_location is None or out_location.get('latitude') is None:
                st.error("⚠️ Please capture your GPS location using the button above.")
            else:
                is_valid = True
                out_loc_str = in_loc 
                u_lat, u_lon = out_location['latitude'], out_location['longitude']
                
                if in_type == "Office":
                    dist = calculate_distance(u_lat, u_lon, OFFICE_LAT, OFFICE_LON)
                    if dist > 100:
                        st.error(f"❌ Verification Failed: You are {int(dist)} meters away from the Office. You must punch out from the office.")
                        is_valid = False
                else:
                    t_lat, t_lon = client_coords.get(in_loc, (None, None))
                    if t_lat is not None:
                        dist = calculate_distance(u_lat, u_lon, t_lat, t_lon)
                        if dist > 200:
                            st.error(f"❌ Verification Failed: You are {int(dist)} meters away from the Client. You must punch out from the client's location.")
                            is_valid = False
                            
                if is_valid:
                    auto_out_time = get_current_ist_time()
                    punch_out(current_date, st.session_state.current_user, auto_out_time, out_loc_str)
                    st.rerun()

    # PHASE 3: SHIFT COMPLETED
    elif status == "punched_out":
        st.error(f"🔴 **Shift Completed:** Punched In at {in_time} | Punched Out at {out_time}")
        st.write("Your timesheet for today is securely locked. Have a great evening!")