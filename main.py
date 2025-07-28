import streamlit as st
import pandas as pd
import numpy as np
import re
from urllib.parse import urlparse
import io
from datetime import datetime
import logging

# Configure page
st.set_page_config(
    page_title="HubSpot to Reevo Data Importer",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .step-header {
        background: linear-gradient(90deg, #1f77b4, #17becf);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .data-section {
        background-color: #f8f9fa;
        border: 2px solid #dee2e6;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
    }
    .raw-data-section {
        background-color: #fff3cd;
        border: 2px solid #ffc107;
        border-radius: 10px;
        padding: 1.5rem;
    }
    .cleaned-data-section {
        background-color: #d1ecf1;
        border: 2px solid #17a2b8;
        border-radius: 10px;
        padding: 1.5rem;
    }
    .final-data-section {
        background-color: #d4edda;
        border: 2px solid #28a745;
        border-radius: 10px;
        padding: 1.5rem;
    }
    .cleaning-step {
        background-color: #e7f3ff;
        border-left: 4px solid #2196f3;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .error-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

class HubSpotReevoTransformer:
    def __init__(self):
        # EXACT field mapping from Reevo template
        self.hubspot_to_reevo_mapping = {
            'First Name': 'contact_first_name',
            'Last Name': 'contact_last_name', 
            'Email': 'contact_primary_email',
            'Personal Linkedin URL': 'contact_linkedin_url',
            'Job Title': 'contact_account_role_title',
            'Company Name': 'account_name',
            'Website': 'account_domain_name',
            'Company Linkedin URL': 'account_linkedin_url'
        }
        
        # Phone fields in priority order
        self.phone_fields = ['Mobile', 'Direct', 'Office']
        
        # EXACT Reevo template headers
        self.reevo_template_headers = [
            'contact_owner_id', 'contact_first_name', 'contact_last_name',
            'contact_primary_email', 'contact_primary_phone_number', 'contact_linkedin_url',
            'contact_account_role_title', 'account_owner_id', 'account_name',
            'account_domain_name', 'account_linkedin_url'
        ]
        
        # Cleaning steps tracker
        self.cleaning_steps = []
    
    def validate_email(self, email):
        """Validate email format"""
        if pd.isna(email) or email == '':
            return False
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, str(email)))
    
    def clean_domain(self, website):
        """Extract and clean domain from website URL"""
        if pd.isna(website) or website == '':
            return ''
        
        original_website = str(website).strip()
        
        # Track cleaning step
        cleaning_step = {
            'field': 'Website → Domain',
            'original': original_website,
            'action': 'Extract domain'
        }
        
        # Add protocol if missing
        if not original_website.startswith(('http://', 'https://')):
            website = 'https://' + original_website
            cleaning_step['action'] += ', Add https://'
        else:
            website = original_website
            
        try:
            parsed = urlparse(website)
            domain = parsed.netloc or parsed.path
            domain = domain.replace('www.', '').lower()
            
            if domain != original_website.lower():
                cleaning_step['cleaned'] = domain
                cleaning_step['action'] += f', Remove www/protocols'
                self.cleaning_steps.append(cleaning_step)
            
            return domain
        except:
            # Fallback to basic string cleaning
            domain = original_website.replace('http://', '').replace('https://', '').replace('www.', '')
            domain = domain.split('/')[0].lower()
            cleaning_step['cleaned'] = domain
            cleaning_step['action'] += ', Fallback cleaning'
            self.cleaning_steps.append(cleaning_step)
            return domain
    
    def clean_phone(self, phone):
        """Clean and standardize phone number format"""
        if pd.isna(phone) or phone == '':
            return ''
        
        original_phone = str(phone).strip()
        
        # Basic phone cleaning
        cleaned_phone = re.sub(r'[^\d\+\-\(\)\s]', '', original_phone)
        
        # Track cleaning if change occurred
        if cleaned_phone != original_phone:
            self.cleaning_steps.append({
                'field': 'Phone Number',
                'original': original_phone,
                'cleaned': cleaned_phone,
                'action': 'Remove special characters'
            })
        
        return cleaned_phone
    
    def get_best_phone(self, record):
        """Get the first available phone number in priority order with tracking"""
        phone_selection = {
            'selected_field': None,
            'selected_value': '',
            'available_phones': {}
        }
        
        # Check all phone fields
        for field in self.phone_fields:
            if field in record and pd.notna(record[field]) and str(record[field]).strip():
                phone_value = self.clean_phone(record[field])
                phone_selection['available_phones'][field] = phone_value
                
                # Select first available (highest priority)
                if not phone_selection['selected_field']:
                    phone_selection['selected_field'] = field
                    phone_selection['selected_value'] = phone_value
        
        # Track phone selection logic
        if phone_selection['selected_field']:
            self.cleaning_steps.append({
                'field': 'Phone Selection',
                'original': f"Available: {', '.join(phone_selection['available_phones'].keys())}",
                'cleaned': phone_selection['selected_value'],
                'action': f"Selected {phone_selection['selected_field']} (highest priority)"
            })
        
        return phone_selection['selected_value']
    
    def transform_record(self, record, record_index=0):
        """Transform a single HubSpot record with detailed tracking"""
        transformed = {}
        record_cleaning_steps = []
        
        # Clear previous steps for this record
        self.cleaning_steps = []
        
        # Initialize all Reevo fields
        for header in self.reevo_template_headers:
            transformed[header] = ''
        
        # Map standard fields with cleaning tracking
        for hubspot_field, reevo_field in self.hubspot_to_reevo_mapping.items():
            if hubspot_field in record and pd.notna(record[hubspot_field]):
                original_value = str(record[hubspot_field]).strip()
                
                if reevo_field == 'account_domain_name':
                    cleaned_value = self.clean_domain(original_value)
                else:
                    cleaned_value = original_value
                
                transformed[reevo_field] = cleaned_value
                
                # Track basic field mapping
                if original_value != cleaned_value:
                    record_cleaning_steps.append({
                        'step': f"Clean {hubspot_field}",
                        'original': original_value,
                        'cleaned': cleaned_value
                    })
        
        # Handle phone number with priority logic
        transformed['contact_primary_phone_number'] = self.get_best_phone(record)
        
        return transformed, self.cleaning_steps
    
    def validate_record(self, record, index):
        """Validate record with detailed error tracking"""
        errors = []
        warnings = []
        
        # Required field checks
        required_checks = [
            ('contact_first_name', 'First Name'),
            ('contact_last_name', 'Last Name'),
            ('account_name', 'Company Name'),
            ('account_domain_name', 'Website/Domain')
        ]
        
        for field_name, display_name in required_checks:
            if not record.get(field_name, '').strip():
                errors.append(f"Row {index + 1}: Missing required field '{display_name}'")
        
        # Email OR phone requirement
        has_email = record.get('contact_primary_email', '').strip() != ''
        has_phone = record.get('contact_primary_phone_number', '').strip() != ''
        
        if not has_email and not has_phone:
            errors.append(f"Row {index + 1}: Must have either email or phone number")
        
        # Email format validation
        if has_email and not self.validate_email(record['contact_primary_email']):
            errors.append(f"Row {index + 1}: Invalid email format")
        
        # LinkedIn URL checks
        linkedin_fields = [
            ('contact_linkedin_url', 'Personal LinkedIn'),
            ('account_linkedin_url', 'Company LinkedIn')
        ]
        
        for field_name, display_name in linkedin_fields:
            url = record.get(field_name, '')
            if url and 'linkedin.com' not in url.lower():
                warnings.append(f"Row {index + 1}: {display_name} URL may be invalid")
        
        return errors, warnings

def show_data_cleaning_demo():
    """Show examples of data cleaning with real data"""
    st.subheader("🧹 Data Cleaning Examples")
    
    # Example transformations
    examples = [
        {
            "Field": "Website → Domain",
            "Original": "ayrwellness.com",
            "Cleaned": "ayrwellness.com",
            "Action": "Already clean domain"
        },
        {
            "Field": "Website → Domain", 
            "Original": "https://www.terrascend.com/",
            "Cleaned": "terrascend.com",
            "Action": "Remove https://, www, trailing slash"
        },
        {
            "Field": "Phone Selection",
            "Original": "Mobile: +1 203-451-7659, Direct: +1 203-557-0353",
            "Cleaned": "+1 203-451-7659",
            "Action": "Select Mobile (highest priority)"
        },
        {
            "Field": "Email Validation",
            "Original": "benjamin.rogers@ayrwellness.com",
            "Cleaned": "benjamin.rogers@ayrwellness.com",
            "Action": "Valid format ✅"
        }
    ]
    
    examples_df = pd.DataFrame(examples)
    st.dataframe(examples_df, use_container_width=True, hide_index=True)

def main():
    st.markdown('<h1 class="main-header">🔄 HubSpot to Reevo Data Importer</h1>', unsafe_allow_html=True)
    
    st.markdown("""
    **Complete Data Transformation Pipeline** - Transform HubSpot contact exports into Reevo-ready format.
    See every step of the cleaning, transformation, and validation process with your actual data.
    """)
    
    # Initialize session state
    if 'step' not in st.session_state:
        st.session_state.step = 1
    if 'raw_data' not in st.session_state:
        st.session_state.raw_data = None
    if 'transformed_data' not in st.session_state:
        st.session_state.transformed_data = None
    if 'cleaning_log' not in st.session_state:
        st.session_state.cleaning_log = []
    
    transformer = HubSpotReevoTransformer()
    
    # Sidebar with process overview
    st.sidebar.title("🔄 Import Process")
    process_steps = [
        "1. 📁 Raw Data Analysis",
        "2. 🗺️ Field Mapping", 
        "3. 🧹 Data Cleaning",
        "4. ✅ Data Validation",
        "5. 📥 Reevo Import File"
    ]
    
    for i, step_name in enumerate(process_steps, 1):
        if st.session_state.step >= i:
            st.sidebar.success(step_name)
        else:
            st.sidebar.info(step_name)
    
    # Data cleaning examples
    with st.sidebar.expander("🧹 Cleaning Examples"):
        show_data_cleaning_demo()
    
    # Step 1: Raw Data Analysis
    if st.session_state.step >= 1:
        st.markdown('<div class="step-header"><h2>Step 1: 📁 Raw HubSpot Data Analysis</h2></div>', unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "Upload your HubSpot CSV export",
            type=['csv'],
            help="Upload the raw HubSpot export containing up to 73 columns of contact and company data"
        )
        
        if uploaded_file is not None:
            try:
                raw_df = pd.read_csv(uploaded_file)
                st.session_state.raw_data = raw_df
                
                # Raw data overview
                st.markdown('<div class="raw-data-section">', unsafe_allow_html=True)
                st.subheader("📊 Raw Data Overview")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Records", len(raw_df))
                with col2:
                    st.metric("Total Columns", len(raw_df.columns))
                with col3:
                    memory_usage = raw_df.memory_usage(deep=True).sum() / 1024
                    st.metric("Memory Usage", f"{memory_usage:.1f} KB")
                with col4:
                    st.metric("File Size", f"{uploaded_file.size / 1024:.1f} KB")
                
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Show sample raw data
                st.subheader("🔍 Raw Data Sample")
                st.write("**First 3 records from your HubSpot export:**")
                
                # Show key fields only for readability
                key_fields = ['Profile ID', 'First Name', 'Last Name', 'Email', 'Mobile', 'Direct', 
                             'Job Title', 'Company Name', 'Website', 'Company Linkedin URL']
                available_key_fields = [field for field in key_fields if field in raw_df.columns]
                
                sample_data = raw_df[available_key_fields].head(3)
                st.dataframe(sample_data, use_container_width=True)
                
                # Data quality analysis
                st.subheader("📈 Data Quality Analysis")
                
                # Analyze completeness of key fields
                quality_data = []
                target_fields = list(transformer.hubspot_to_reevo_mapping.keys()) + transformer.phone_fields
                
                for field in target_fields:
                    if field in raw_df.columns:
                        filled_count = raw_df[field].notna().sum()
                        empty_count = len(raw_df) - filled_count
                        fill_rate = (filled_count / len(raw_df)) * 100
                        
                        quality_data.append({
                            "Field": field,
                            "Filled": filled_count,
                            "Empty": empty_count,
                            "Fill Rate": f"{fill_rate:.1f}%",
                            "Status": "✅ Good" if fill_rate >= 80 else "⚠️ Needs Review" if fill_rate >= 50 else "❌ Poor"
                        })
                    else:
                        quality_data.append({
                            "Field": field,
                            "Filled": 0,
                            "Empty": len(raw_df),
                            "Fill Rate": "0.0%",
                            "Status": "❌ Missing"
                        })
                
                quality_df = pd.DataFrame(quality_data)
                st.dataframe(quality_df, use_container_width=True, hide_index=True)
                
                # Identify potential issues
                issues_found = []
                
                # Check for missing required fields
                missing_fields = [field for field in transformer.hubspot_to_reevo_mapping.keys() 
                                if field not in raw_df.columns]
                if missing_fields:
                    issues_found.append(f"Missing fields: {', '.join(missing_fields)}")
                
                # Check email/phone coverage
                email_coverage = (raw_df['Email'].notna().sum() / len(raw_df)) * 100 if 'Email' in raw_df.columns else 0
                phone_coverage = 0
                for phone_field in transformer.phone_fields:
                    if phone_field in raw_df.columns:
                        phone_coverage = max(phone_coverage, (raw_df[phone_field].notna().sum() / len(raw_df)) * 100)
                
                contact_coverage = len(raw_df[(raw_df['Email'].notna()) | 
                                            (raw_df[transformer.phone_fields].notna().any(axis=1))]) / len(raw_df) * 100
                
                if contact_coverage < 90:
                    issues_found.append(f"Only {contact_coverage:.1f}% of records have email OR phone")
                
                if issues_found:
                    st.markdown('<div class="warning-box">', unsafe_allow_html=True)
                    st.warning("⚠️ **Data Quality Issues Found:**")
                    for issue in issues_found:
                        st.write(f"• {issue}")
                    st.write("These issues will be addressed in the cleaning process.")
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="success-box">', unsafe_allow_html=True)
                    st.success("✅ **Data quality looks good!** Ready for transformation.")
                    st.markdown('</div>', unsafe_allow_html=True)
                
                if st.button("Proceed to Field Mapping", type="primary"):
                    st.session_state.step = 2
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
    
    # Step 2: Field Mapping
    if st.session_state.step >= 2 and st.session_state.raw_data is not None:
        st.markdown('<div class="step-header"><h2>Step 2: 🗺️ Field Mapping Analysis</h2></div>', unsafe_allow_html=True)
        
        raw_df = st.session_state.raw_data
        
        # Show the exact mapping
        st.subheader("📋 HubSpot → Reevo Field Mapping")
        st.write("**Exact mapping based on Reevo import template:**")
        
        mapping_data = []
        for hubspot_field, reevo_field in transformer.hubspot_to_reevo_mapping.items():
            is_available = hubspot_field in raw_df.columns
            
            if is_available:
                sample_values = raw_df[hubspot_field].dropna().head(2).tolist()
                sample_str = " | ".join([str(x)[:30] + "..." if len(str(x)) > 30 else str(x) for x in sample_values])
                filled = raw_df[hubspot_field].notna().sum()
            else:
                sample_str = "⚠️ Field not found in export"
                filled = 0
            
            mapping_data.append({
                "HubSpot Field": hubspot_field,
                "→": "→",
                "Reevo Field": reevo_field,
                "Available": "✅" if is_available else "❌",
                "Sample Data": sample_str,
                "Records": f"{filled}/{len(raw_df)}"
            })
        
        mapping_df = pd.DataFrame(mapping_data)
        st.dataframe(mapping_df, use_container_width=True, hide_index=True)
        
        # Phone number logic explanation
        st.subheader("📱 Phone Number Selection Logic")
        
        phone_logic_data = []
        for i, phone_field in enumerate(transformer.phone_fields):
            priority = i + 1
            available = phone_field in raw_df.columns
            
            if available:
                count = raw_df[phone_field].notna().sum()
                samples = raw_df[phone_field].dropna().head(2).tolist()
                sample_str = " | ".join([str(x) for x in samples])
            else:
                count = 0
                sample_str = "Field not in export"
            
            phone_logic_data.append({
                "Priority": f"#{priority}",
                "Phone Field": phone_field,
                "Available": "✅" if available else "❌",
                "Records": f"{count}/{len(raw_df)}",
                "Sample Values": sample_str
            })
        
        phone_df = pd.DataFrame(phone_logic_data)
        st.dataframe(phone_df, use_container_width=True, hide_index=True)
        
        st.info("💡 **Logic**: The system will use the first available phone number in priority order: Mobile → Direct → Office")
        
        # Preview transformation for first record
        if len(raw_df) > 0:
            st.subheader("🔍 Sample Transformation Preview")
            
            sample_record = raw_df.iloc[0].to_dict()
            transformed_sample, cleaning_steps = transformer.transform_record(sample_record)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown('<div class="raw-data-section">', unsafe_allow_html=True)
                st.write("**📥 Original HubSpot Data:**")
                original_data = {}
                for field in list(transformer.hubspot_to_reevo_mapping.keys()) + transformer.phone_fields:
                    if field in sample_record:
                        original_data[field] = sample_record[field] if pd.notna(sample_record[field]) else "N/A"
                
                for key, value in original_data.items():
                    st.write(f"• **{key}**: {value}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="final-data-section">', unsafe_allow_html=True)
                st.write("**📤 Transformed Reevo Data:**")
                for key, value in transformed_sample.items():
                    display_value = value if value else "Empty"
                    st.write(f"• **{key}**: {display_value}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            # Show cleaning steps applied
            if cleaning_steps:
                st.subheader("🧹 Cleaning Steps Applied")
                for step in cleaning_steps:
                    st.markdown(f'<div class="cleaning-step">', unsafe_allow_html=True)
                    st.write(f"**{step.get('field', 'Unknown')}**: {step.get('action', 'N/A')}")
                    if 'original' in step and 'cleaned' in step:
                        st.write(f"• Before: `{step['original']}`")
                        st.write(f"• After: `{step['cleaned']}`")
                    st.markdown('</div>', unsafe_allow_html=True)
        
        if st.button("Proceed to Data Cleaning", type="primary"):
            st.session_state.step = 3
            st.rerun()
    
    # Step 3: Data Cleaning & Transformation
    if st.session_state.step >= 3 and st.session_state.raw_data is not None:
        st.markdown('<div class="step-header"><h2>Step 3: 🧹 Data Cleaning & Transformation</h2></div>', unsafe_allow_html=True)
        
        raw_df = st.session_state.raw_data
        
        st.write("🔄 **Processing all records through the complete cleaning and transformation pipeline...**")
        
        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        transformed_records = []
        all_cleaning_steps = []
        total_records = len(raw_df)
        
        # Process each record
        for i, (_, record) in enumerate(raw_df.iterrows()):
            transformed_record, cleaning_steps = transformer.transform_record(record.to_dict(), i)
            transformed_records.append(transformed_record)
            
            # Store cleaning steps with record info
            for step in cleaning_steps:
                step['record_index'] = i
                step['record_name'] = f"{record.get('First Name', 'Unknown')} {record.get('Last Name', '')}"
            all_cleaning_steps.extend(cleaning_steps)
            
            # Update progress
            progress = (i + 1) / total_records
            progress_bar.progress(progress)
            status_text.text(f'Processing: {record.get("First Name", "Unknown")} {record.get("Last Name", "")} ({i + 1}/{total_records})')
        
        # Create final DataFrame
        transformed_df = pd.DataFrame(transformed_records, columns=transformer.reevo_template_headers)
        st.session_state.transformed_data = transformed_df
        st.session_state.cleaning_log = all_cleaning_steps
        
        status_text.text('✅ Data cleaning and transformation complete!')
        
        # Show transformation summary
        st.markdown('<div class="cleaned-data-section">', unsafe_allow_html=True)
        st.subheader("📊 Transformation Summary")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Records Processed", len(transformed_df))
        with col2:
            st.metric("Cleaning Steps", len(all_cleaning_steps))
        with col3:
            # Count records with data in key fields
            filled_contacts = (transformed_df['contact_first_name'] != '').sum()
            st.metric("Valid Contacts", filled_contacts)
        with col4:
            filled_accounts = (transformed_df['account_name'] != '').sum()
            st.metric("Valid Accounts", filled_accounts)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Show detailed cleaning log
        st.subheader("🧹 Detailed Cleaning Log")
        
        if all_cleaning_steps:
            # Group cleaning steps by type
            cleaning_summary = {}
            for step in all_cleaning_steps:
                step_type = step.get('field', 'Unknown')
                if step_type not in cleaning_summary:
                    cleaning_summary[step_type] = []
                cleaning_summary[step_type].append(step)
            
            # Display cleaning summary
            for step_type, steps in cleaning_summary.items():
                with st.expander(f"🔧 {step_type} ({len(steps)} operations)"):
                    for step in steps[:10]:  # Show first 10 examples
                        st.markdown(f'<div class="cleaning-step">', unsafe_allow_html=True)
                        st.write(f"**Record {step['record_index'] + 1}** ({step.get('record_name', 'Unknown')})")
                        st.write(f"**Action**: {step.get('action', 'N/A')}")
                        if 'original' in step:
                            st.write(f"• **Original**: `{step['original']}`")
                        if 'cleaned' in step:
                            st.write(f"• **Cleaned**: `{step['cleaned']}`")
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    if len(steps) > 10:
                        st.info(f"... and {len(steps) - 10} more {step_type} operations")
        else:
            st.info("ℹ️ No cleaning operations were needed - your data was already in good format!")
        
        # Show before/after comparison
        st.subheader("📊 Before vs After Comparison")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="raw-data-section">', unsafe_allow_html=True)
            st.write("**📥 Original HubSpot Format**")
            
            # Show relevant original fields
            original_sample = raw_df.head(3)
            display_fields = ['First Name', 'Last Name', 'Email', 'Mobile', 'Company Name', 'Website']
            available_fields = [f for f in display_fields if f in original_sample.columns]
            
            if available_fields:
                st.dataframe(original_sample[available_fields], use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="final-data-section">', unsafe_allow_html=True)
            st.write("**📤 Reevo Import Format**")
            
            # Show key transformed fields
            key_reevo_fields = ['contact_first_name', 'contact_last_name', 'contact_primary_email', 
                              'contact_primary_phone_number', 'account_name', 'account_domain_name']
            st.dataframe(transformed_df[key_reevo_fields].head(3), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Field population analysis
        st.subheader("📈 Field Population Analysis")
        
        population_data = []
        for field in transformer.reevo_template_headers:
            filled_count = (transformed_df[field] != '').sum()
            fill_rate = (filled_count / len(transformed_df)) * 100
            
            # Determine if field is required
            if field in ['contact_first_name', 'contact_last_name', 'account_name', 'account_domain_name']:
                requirement = "Required"
            elif field in ['contact_primary_email', 'contact_primary_phone_number']:
                requirement = "Required (Either/Or)"
            else:
                requirement = "Recommended"
            
            population_data.append({
                "Reevo Field": field,
                "Requirement": requirement,
                "Filled Records": f"{filled_count}/{len(transformed_df)}",
                "Fill Rate": f"{fill_rate:.1f}%",
                "Status": "✅" if (requirement == "Required" and fill_rate == 100) or 
                         (requirement != "Required" and fill_rate >= 0) else "⚠️"
            })
        
        population_df = pd.DataFrame(population_data)
        st.dataframe(population_df, use_container_width=True, hide_index=True)
        
        if st.button("Proceed to Data Validation", type="primary"):
            st.session_state.step = 4
            st.rerun()
    
    # Step 4: Data Validation
    if st.session_state.step >= 4 and st.session_state.transformed_data is not None:
        st.markdown('<div class="step-header"><h2>Step 4: ✅ Data Validation</h2></div>', unsafe_allow_html=True)
        
        transformed_df = st.session_state.transformed_data
        
        st.write("🔍 **Validating all transformed records against Reevo import requirements...**")
        
        # Validation progress
        validation_progress = st.progress(0)
        validation_status = st.empty()
        
        all_errors = []
        all_warnings = []
        valid_records = []
        invalid_records = []
        validation_details = []
        
        # Validate each record
        for i, (_, record) in enumerate(transformed_df.iterrows()):
            errors, warnings = transformer.validate_record(record.to_dict(), i)
            
            # Store detailed validation info
            record_validation = {
                'index': i,
                'name': f"{record.get('contact_first_name', 'Unknown')} {record.get('contact_last_name', '')}",
                'errors': errors,
                'warnings': warnings,
                'status': 'Valid' if not errors else 'Invalid'
            }
            validation_details.append(record_validation)
            
            all_errors.extend(errors)
            all_warnings.extend(warnings)
            
            if errors:
                invalid_records.append(i)
            else:
                valid_records.append(i)
            
            # Update progress
            progress = (i + 1) / len(transformed_df)
            validation_progress.progress(progress)
            validation_status.text(f'Validating: {record_validation["name"]} ({i + 1}/{len(transformed_df)})')
        
        validation_status.text('✅ Validation complete!')
        
        # Validation summary
        st.subheader("📋 Validation Results")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Records", len(transformed_df))
        with col2:
            success_rate = (len(valid_records) / len(transformed_df)) * 100
            st.metric("Valid Records", len(valid_records), delta=f"{success_rate:.1f}%")
        with col3:
            st.metric("Invalid Records", len(invalid_records))
        with col4:
            st.metric("Total Issues", len(all_errors) + len(all_warnings))
        
        # Show validation status for each record
        st.subheader("📊 Per-Record Validation Status")
        
        validation_summary = []
        for detail in validation_details[:20]:  # Show first 20 records
            validation_summary.append({
                "Record": f"#{detail['index'] + 1}",
                "Name": detail['name'],
                "Status": "✅ Valid" if detail['status'] == 'Valid' else "❌ Invalid",
                "Errors": len(detail['errors']),
                "Warnings": len(detail['warnings']),
                "Issues": "; ".join(detail['errors'][:2]) if detail['errors'] else "None"
            })
        
        validation_summary_df = pd.DataFrame(validation_summary)
        st.dataframe(validation_summary_df, use_container_width=True, hide_index=True)
        
        if len(validation_details) > 20:
            st.info(f"Showing first 20 records. Total validation details available for all {len(validation_details)} records.")
        
        # Detailed error analysis
        if all_errors:
            st.markdown('<div class="error-box">', unsafe_allow_html=True)
            st.error(f"❌ **{len(all_errors)} Validation Errors Found**")
            
            # Group errors by type
            error_types = {}
            for error in all_errors:
                error_type = error.split(":")[1].strip() if ":" in error else error
                if error_type not in error_types:
                    error_types[error_type] = []
                error_types[error_type].append(error)
            
            for error_type, errors in error_types.items():
                with st.expander(f"🚨 {error_type} ({len(errors)} occurrences)"):
                    for error in errors[:10]:
                        st.write(f"• {error}")
                    if len(errors) > 10:
                        st.write(f"... and {len(errors) - 10} more similar errors")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Warning analysis
        if all_warnings:
            st.markdown('<div class="warning-box">', unsafe_allow_html=True)
            st.warning(f"⚠️ **{len(all_warnings)} Warnings Found**")
            st.write("These records will still be imported but may need review:")
            
            for warning in all_warnings[:10]:
                st.write(f"• {warning}")
            
            if len(all_warnings) > 10:
                with st.expander(f"Show remaining {len(all_warnings) - 10} warnings"):
                    for warning in all_warnings[10:]:
                        st.write(f"• {warning}")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Show sample valid records
        if valid_records:
            st.subheader("✅ Sample Valid Records")
            st.write("Preview of records ready for Reevo import:")
            
            valid_sample = transformed_df.iloc[valid_records[:5]]
            st.dataframe(valid_sample, use_container_width=True)
        
        # Import readiness assessment
        if len(valid_records) > 0:
            st.markdown('<div class="success-box">', unsafe_allow_html=True)
            if len(invalid_records) == 0:
                st.success("🎉 **Perfect! All records passed validation**")
                st.write("Your data is ready for import with no issues.")
            else:
                st.success(f"✅ **{len(valid_records)} records are ready for import**")
                st.info(f"💡 **Recommendation**: Import the {len(valid_records)} valid records now. "
                        f"Fix the {len(invalid_records)} invalid records and import them separately.")
            st.markdown('</div>', unsafe_allow_html=True)
            
            if st.button("Generate Reevo Import File", type="primary"):
                st.session_state.step = 5
                st.rerun()
        else:
            st.markdown('<div class="error-box">', unsafe_allow_html=True)
            st.error("❌ **No valid records found**")
            st.write("All records have validation errors that must be fixed before import.")
            st.write("**Next Steps:**")
            st.write("1. Review the validation errors above")
            st.write("2. Fix the issues in your source HubSpot data")
            st.write("3. Re-export and upload the corrected file")
            st.markdown('</div>', unsafe_allow_html=True)
    
    # Step 5: Final Import File
    if st.session_state.step >= 5 and st.session_state.transformed_data is not None:
        st.markdown('<div class="step-header"><h2>Step 5: 📥 Generate Reevo Import File</h2></div>', unsafe_allow_html=True)
        
        transformed_df = st.session_state.transformed_data
        cleaning_log = st.session_state.cleaning_log
        
        # Get valid records only
        valid_records = []
        for i, (_, record) in enumerate(transformed_df.iterrows()):
            errors, _ = transformer.validate_record(record.to_dict(), i)
            if not errors:
                valid_records.append(i)
        
        final_df = transformed_df.iloc[valid_records].copy()
        
        # Final success message
        st.markdown('<div class="final-data-section">', unsafe_allow_html=True)
        st.success(f"🎉 **Import file ready!** {len(final_df)} validated records prepared for Reevo import.")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Final statistics
        st.subheader("📊 Final Import Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Ready for Import", len(final_df))
        with col2:
            success_rate = (len(final_df) / len(st.session_state.raw_data)) * 100
            st.metric("Success Rate", f"{success_rate:.1f}%")
        with col3:
            st.metric("Cleaning Operations", len(cleaning_log))
        with col4:
            file_size = len(final_df) * len(transformer.reevo_template_headers) * 25
            st.metric("File Size", f"{file_size / 1024:.1f} KB")
        
        # Show final data preview
        st.subheader("📋 Final Import File Preview")
        st.write("**This is exactly what will be imported into Reevo:**")
        
        # Show all columns but limit rows
        st.dataframe(final_df.head(10), use_container_width=True)
        
        # Create download
        csv_buffer = io.StringIO()
        final_df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"reevo_import_ready_{timestamp}.csv"
        
        # Download button
        st.download_button(
            label="📥 Download Reevo Import File",
            data=csv_data,
            file_name=filename,
            mime="text/csv",
            type="primary",
            help="Download the validated, cleaned, and formatted file ready for Reevo import"
        )
        
        # Complete process summary
        st.subheader("📋 Complete Process Summary")
        
        with st.expander("🔄 Full Transformation Journey", expanded=True):
            process_summary = {
                "Stage": [
                    "1. Raw HubSpot Data",
                    "2. Field Mapping", 
                    "3. Data Cleaning",
                    "4. Data Validation",
                    "5. Final Import File"
                ],
                "Records": [
                    len(st.session_state.raw_data),
                    len(st.session_state.raw_data),
                    len(transformed_df),
                    len(final_df),
                    len(final_df)
                ],
                "Key Actions": [
                    f"Loaded {len(st.session_state.raw_data.columns)} columns of raw data",
                    f"Mapped {len(transformer.hubspot_to_reevo_mapping)} core fields",
                    f"Applied {len(cleaning_log)} cleaning operations", 
                    f"Validated against Reevo requirements",
                    "Generated final import-ready file"
                ],
                "Data Quality": [
                    "Raw export format",
                    "Field alignment complete",
                    "Data cleaned & standardized",
                    "Requirements validated",
                    "✅ Import ready"
                ]
            }
            
            summary_df = pd.DataFrame(process_summary)
            st.dataframe(summary_df, use_container_width=True, hide_index=True)
        
        # Import instructions
        st.subheader("🚀 Next Steps: Import to Reevo")
        
        st.markdown("""
        **Your file is now ready for Reevo import! Follow these steps:**
        
        1. **📥 Download** the file using the button above
        2. **🔐 Log into** your Reevo admin panel  
        3. **📁 Navigate** to the Import section
        4. **📊 Select** "Contact & Account Import"
        5. **📤 Upload** the downloaded CSV file
        6. **👀 Review** the import preview (all fields should map automatically)
        7. **▶️ Execute** the import
        8. **✅ Verify** imported contacts and accounts in Reevo
        
        **🔥 Key Benefits of This File:**
        - ✅ **Perfect Template Match**: Uses exact Reevo field structure
        - ✅ **Data Cleaned**: All transformations applied automatically  
        - ✅ **Validated**: Only quality records included
        - ✅ **No Manual Work**: Ready for direct import, no cleanup needed
        """)
        
        # Reset option
        if st.button("🔄 Process Another File", type="secondary"):
            for key in ['step', 'raw_data', 'transformed_data', 'cleaning_log']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

if __name__ == "__main__":
    main()
