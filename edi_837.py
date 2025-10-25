from datetime import datetime

DEFAULT_SEG = "~"
DEFAULT_ELEM = "*"

def build_837(
    isa_ctrl:int,
    gs_ctrl:int,
    st_ctrl:int,
    sender_id:str,
    receiver_id:str,
    billing_provider_npi:str,
    patient_name:str,
    patient_id:str,
    claim_id:str,
    claim_amount:str,
    dos_start:str,
    dos_end:str=None
):
    now = datetime.now()
    dos_segment = f"DTP*472*D8*{dos_start}~" if not dos_end else f"DTP*472*RD8*{dos_start}-{dos_end}~"

    edi = ""
    edi += f"ISA*00*          *00*          *ZZ*{sender_id:<15}*ZZ*{receiver_id:<15}*{now.strftime('%y%m%d')}*{now.strftime('%H%M')}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
    edi += f"GS*HC*{sender_id}*{receiver_id}*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*{gs_ctrl}*X*005010X222A1~\n"
    edi += f"ST*837*{st_ctrl}*005010X222A1~\n"
    edi += f"BHT*0019*00*{claim_id}*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*CH~\n"
    edi += "NM1*41*2*BILLING PROVIDER*****46*12345~\n"
    edi += f"PER*IC*BILLING OFFICE*TE*8005551212~\n"
    edi += "NM1*40*2*PAYER NAME*****46*99999~\n"
    edi += "HL*1**20*1~\n"
    edi += "NM1*85*2*BUDDHA CLINIC*****XX*" + billing_provider_npi + "~\n"
    edi += "N3*123 MAIN STREET~\nN4*LUCKNOW*UP*226001~\n"
    edi += "REF*EI*123456789~\n"
    edi += "HL*2*1*22*0~\n"
    edi += f"NM1*IL*1*{patient_name}****MI*{patient_id}~\n"
    edi += dos_segment
    edi += f"CLM*{claim_id}*{claim_amount}***11:B:1*Y*A*Y*I~\n"
    edi += "HI*BK:12345~\n"
    edi += "LX*1~\n"
    edi += "SV1*HC:99213*100*UN*1***1~\n"
    edi += "SE*20*{st_ctrl}~\n"
    edi += f"GE*1*{gs_ctrl}~\n"
    edi += f"IEA*1*{isa_ctrl:09d}~"
    return edi
