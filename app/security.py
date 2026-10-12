import re


def redact(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[联系方式已隔离]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[联系方式已隔离]", text)
    text = re.sub(r"(?<!\d)\d{17}[0-9Xx](?!\d)", "[身份信息已隔离]", text)
    sensitive = r"性别|年龄|出生|生日|民族|婚姻|婚育|籍贯|姓名|学校|毕业院校|大学|学院|身份证|政治面貌|党员|团员|985|211|双一流|QS\s*排名"
    # Remove complete clauses to avoid leaving proxy signals such as school names.
    return "\n".join(line for line in re.split(r"[\n；;]", text) if not re.search(sensitive, line))
