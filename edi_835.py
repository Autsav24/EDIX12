from datetime import datetime

DEFAULT_SEG = "~"
DEFAULT_ELEM = "*"

def build_835(
    isa_ctrl:int,
    gs_ctrl:int,
    st_ctrl:int,
    payer_name:str,
    payer_id:str,
    provider_npi:str,
    claim_id:str,
    patient_name:str,
    paid_amount:str,
    check_number:str,
    payment_date:str
):
    now = datetime.now()
    edi = ""
    edi += f"ISA*00*          *00*          *ZZ*{payer_id:<15}*ZZ*RECEIVERID     *{now.strftime('%y%m%d')}*{now.strftime('%H%M')}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
    edi += f"GS*HP*{payer_id}*RECEIVER*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*{gs_ctrl}*X*005010X221A1~\n"
    edi += f"ST*835*{st_ctrl}*005010X221A1~\n"
    edi += f"BPR*I*{paid_amount}*C*CHK*01*999999999*DA*123456789*{now.strftime('%Y%m%d')}~\n"
    edi += f"TRN*1*{check_number}*{payer_id}~\n"
    edi += f"DTM*405*{payment_date}~\n"
    edi += f"N1*PR*{payer_name}*PI*{payer_id}~\n"
    edi += f"N1*PE*BUDDHA CLINIC*XX*{provider_npi}~\n"
    edi += f"CLP*{claim_id}*1*150*{paid_amount}**MC*{patient_name}*12*1~\n"
    edi += "CAS*CO*45*50~\n"
    edi += "NM1*QC*1*" + patient_name + "****MI*123456789~\n"
    edi += f"DTM*232*{payment_date}~\n"
    edi += f"DTM*233*{payment_date}~\n"
    edi += "SE*12*{st_ctrl}~\n"
    edi += f"GE*1*{gs_ctrl}~\n"
    edi += f"IEA*1*{isa_ctrl:09d}~"
    return edi
